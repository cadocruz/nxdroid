// The Apple media frameworks the host names, on bionic. Three families have real backends: the AudioUnit
// output plays through AAudio (hle_audio.c's 48 kHz stereo PCM), AudioConverter decodes AAC to PCM16 through
// MediaCodec (hle_movie.c's movie tracks), and VideoToolbox's H.264 decoder decodes through MediaCodec into an
// NV12 CVPixelBufferRef (hle_movie_avc.c). The rest fail, each family saying so once with a [RED] line, so
// that the Android link set is complete: an AudioConverter for another format pair or an unsupported
// AudioUnit component type is refused. The host's own fallbacks then apply: the silent sink paces the game's
// audio in real time.
#include "../host/dm.h"   // LOG
#include <AudioToolbox/AudioToolbox.h>
#include <VideoToolbox/VideoToolbox.h>
#include <aaudio/AAudio.h>
#include <media/NdkMediaCodec.h>
#include <media/NdkMediaFormat.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>

enum { kStubFailed = -50 /* paramErr: no component, converter or session exists on this platform */ };
static void said(const char *what) { LOG("[RED] %s is not implemented on this platform: the Apple framework calls fail here (interface stubs, dm/android/apple_stubs.c)", what); }

// ---- AudioToolbox: output units (AAudio) ----
struct OpaqueAudioComponentInstance {
    AudioStreamBasicDescription fmt;
    AURenderCallbackStruct cb;
    AAudioStream *stream;
};

static aaudio_data_callback_result_t aaudio_data_cb(AAudioStream *stream, void *userData, void *audioData, int32_t numFrames) {
    (void)stream;
    struct OpaqueAudioComponentInstance *u = (struct OpaqueAudioComponentInstance *)userData;
    if (!u || !u->cb.inputProc) {
        memset(audioData, 0, (size_t)numFrames * (u && u->fmt.mChannelsPerFrame ? u->fmt.mChannelsPerFrame : 2) * sizeof(int16_t));
        return AAUDIO_CALLBACK_RESULT_CONTINUE;
    }
    UInt32 ch = u->fmt.mChannelsPerFrame > 0 ? u->fmt.mChannelsPerFrame : 2;
    AudioBufferList bl;
    bl.mNumberBuffers = 1;
    bl.mBuffers[0].mNumberChannels = ch;
    bl.mBuffers[0].mDataByteSize = (UInt32)numFrames * ch * (UInt32)sizeof(int16_t);
    bl.mBuffers[0].mData = audioData;

    AudioUnitRenderActionFlags flags = 0;
    AudioTimeStamp ts = {0};
    u->cb.inputProc(u->cb.inputProcRefCon, &flags, &ts, 0, (UInt32)numFrames, &bl);
    return AAUDIO_CALLBACK_RESULT_CONTINUE;
}

AudioComponent AudioComponentFindNext(AudioComponent after, const AudioComponentDescription *desc) {
    (void)after;
    if (desc && desc->componentType == kAudioUnitType_Output) {
        return (AudioComponent)1;
    }
    static int once;
    if (!once++) said("audio output through an AudioUnit (unsupported component type)");
    return NULL;
}

OSStatus AudioComponentInstanceNew(AudioComponent c, AudioComponentInstance *out) {
    if (!c || !out) return kStubFailed;
    struct OpaqueAudioComponentInstance *u = (struct OpaqueAudioComponentInstance *)calloc(1, sizeof(*u));
    if (!u) return kStubFailed;
    *out = (AudioComponentInstance)u;
    return noErr;
}

OSStatus AudioComponentInstanceDispose(AudioComponentInstance i) {
    if (!i) return kStubFailed;
    struct OpaqueAudioComponentInstance *u = (struct OpaqueAudioComponentInstance *)i;
    if (u->stream) {
        AAudioStream_requestStop(u->stream);
        AAudioStream_close(u->stream);
        u->stream = NULL;
    }
    free(u);
    return noErr;
}

OSStatus AudioUnitSetProperty(AudioUnit u, AudioUnitPropertyID id, AudioUnitScope scope, AudioUnitElement el, const void *data, UInt32 size) {
    (void)scope; (void)el;
    if (!u) return kStubFailed;
    struct OpaqueAudioComponentInstance *inst = (struct OpaqueAudioComponentInstance *)u;
    if (id == kAudioUnitProperty_StreamFormat && data && size >= sizeof(AudioStreamBasicDescription)) {
        memcpy(&inst->fmt, data, sizeof(AudioStreamBasicDescription));
        return noErr;
    }
    if (id == kAudioUnitProperty_SetRenderCallback && data && size >= sizeof(AURenderCallbackStruct)) {
        memcpy(&inst->cb, data, sizeof(AURenderCallbackStruct));
        return noErr;
    }
    return noErr;
}

OSStatus AudioUnitGetProperty(AudioUnit u, AudioUnitPropertyID id, AudioUnitScope scope, AudioUnitElement el, void *data, UInt32 *size) {
    (void)scope; (void)el;
    if (!u) return kStubFailed;
    struct OpaqueAudioComponentInstance *inst = (struct OpaqueAudioComponentInstance *)u;
    if (id == kAudioUnitProperty_StreamFormat && data && size && *size >= sizeof(AudioStreamBasicDescription)) {
        memcpy(data, &inst->fmt, sizeof(AudioStreamBasicDescription));
        *size = sizeof(AudioStreamBasicDescription);
        return noErr;
    }
    return kStubFailed;
}

OSStatus AudioUnitInitialize(AudioUnit u) {
    if (!u) return kStubFailed;
    struct OpaqueAudioComponentInstance *inst = (struct OpaqueAudioComponentInstance *)u;
    if (inst->stream) {
        aaudio_stream_state_t st = AAudioStream_getState(inst->stream);
        if (st != AAUDIO_STREAM_STATE_DISCONNECTED && st != AAUDIO_STREAM_STATE_CLOSING && st != AAUDIO_STREAM_STATE_CLOSED) {
            return noErr;
        }
        AAudioStream_close(inst->stream);
        inst->stream = NULL;
    }

    AAudioStreamBuilder *b = NULL;
    aaudio_result_t res = AAudio_createStreamBuilder(&b);
    if (res != AAUDIO_OK || !b) {
        LOG("[RED] AudioUnitInitialize: AAudio_createStreamBuilder failed (%d: %s)", res, AAudio_convertResultToText(res));
        return kStubFailed;
    }

    int32_t rate = (int32_t)(inst->fmt.mSampleRate > 0 ? inst->fmt.mSampleRate : 48000);
    int32_t channels = (int32_t)(inst->fmt.mChannelsPerFrame > 0 ? inst->fmt.mChannelsPerFrame : 2);
    int32_t frames_per_cb = rate / 200; // 5 ms frames (240 at 48 kHz), matching audren block size

    AAudioStreamBuilder_setDirection(b, AAUDIO_DIRECTION_OUTPUT);
    AAudioStreamBuilder_setSampleRate(b, rate);
    AAudioStreamBuilder_setChannelCount(b, channels);
    AAudioStreamBuilder_setFormat(b, AAUDIO_FORMAT_PCM_I16);
    AAudioStreamBuilder_setSharingMode(b, AAUDIO_SHARING_MODE_SHARED);
    AAudioStreamBuilder_setUsage(b, AAUDIO_USAGE_GAME);
    AAudioStreamBuilder_setContentType(b, AAUDIO_CONTENT_TYPE_MUSIC);
    AAudioStreamBuilder_setPerformanceMode(b, AAUDIO_PERFORMANCE_MODE_LOW_LATENCY);
    AAudioStreamBuilder_setFramesPerDataCallback(b, frames_per_cb);
    AAudioStreamBuilder_setBufferCapacityInFrames(b, frames_per_cb * 8);
    AAudioStreamBuilder_setDataCallback(b, aaudio_data_cb, inst);

    res = AAudioStreamBuilder_openStream(b, &inst->stream);
    AAudioStreamBuilder_delete(b);
    if (res != AAUDIO_OK || !inst->stream) {
        LOG("[RED] AudioUnitInitialize: AAudioStreamBuilder_openStream failed (%d: %s)", res, AAudio_convertResultToText(res));
        inst->stream = NULL;
        return kStubFailed;
    }
    int32_t burst = AAudioStream_getFramesPerBurst(inst->stream);
    if (burst > 0) {
        int32_t target_buf = burst * 2;
        if (target_buf < frames_per_cb * 2) target_buf = frames_per_cb * 2;
        AAudioStream_setBufferSizeInFrames(inst->stream, target_buf);
    }
    LOG("AudioUnit (AAudio) initialized: %d Hz, %d channels, frames/cb %d, burst %d, buf %d, capacity %d, low-latency",
        rate, channels, frames_per_cb, burst,
        AAudioStream_getBufferSizeInFrames(inst->stream),
        AAudioStream_getBufferCapacityInFrames(inst->stream));
    return noErr;
}

OSStatus AudioUnitUninitialize(AudioUnit u) {
    if (!u) return kStubFailed;
    struct OpaqueAudioComponentInstance *inst = (struct OpaqueAudioComponentInstance *)u;
    if (inst->stream) {
        AAudioStream_requestStop(inst->stream);
        AAudioStream_close(inst->stream);
        inst->stream = NULL;
    }
    return noErr;
}

OSStatus AudioOutputUnitStart(AudioUnit u) {
    if (!u) return kStubFailed;
    struct OpaqueAudioComponentInstance *inst = (struct OpaqueAudioComponentInstance *)u;
    if (!inst->stream || AAudioStream_getState(inst->stream) == AAUDIO_STREAM_STATE_DISCONNECTED) {
        AudioUnitInitialize(u);
    }
    if (!inst->stream) return kStubFailed;
    aaudio_result_t res = AAudioStream_requestStart(inst->stream);
    if (res != AAUDIO_OK) {
        LOG("[RED] AudioOutputUnitStart: AAudioStream_requestStart failed (%d: %s)", res, AAudio_convertResultToText(res));
        AAudioStream_close(inst->stream);
        inst->stream = NULL;
        return kStubFailed;
    }
    return noErr;
}

OSStatus AudioOutputUnitStop(AudioUnit u) {
    if (!u || !u->stream) return kStubFailed;
    aaudio_result_t res = AAudioStream_requestStop(u->stream);
    if (res != AAUDIO_OK) {
        LOG("[RED] AudioOutputUnitStop: AAudioStream_requestStop failed (%d: %s)", res, AAudio_convertResultToText(res));
        return kStubFailed;
    }
    return noErr;
}
// ---- AudioToolbox: the AAC converter, through MediaCodec ----
// hle_movie.c's AAC decoder (md_aac_open / md_aac) as AudioToolbox serves it: AudioConverterNew from MPEG-4 AAC to interleaved signed 16-bit PCM,
// the configuration as a magic cookie (an MPEG-4 ES descriptor around the AudioSpecificConfig, or the AudioSpecificConfig alone), then
// AudioConverterFillComplexBuffer, whose input callback hands over one raw AAC frame. MediaCodec's AAC decoder ("audio/mp4a-latm", csd-0 =
// AudioSpecificConfig) decodes it; each of its output buffers is one decoded frame (1024 samples per channel, 2048 with SBR), and a fill hands out
// at most one, as AudioToolbox does for the one packet the callback gives: the game sizes its outputs by one frame (hle_movie.c,
// GetOutputBufferSize). MediaCodec may return a frame one packet late; the frames it has not handed out yet wait in a short queue. Its output is
// PCM16 at the stream's own rate (no resampling, as the host asks for the input rate); a channel count other than the one asked for is mixed to it
// (mono doubled, stereo averaged, otherwise channels dropped or silent).
#define AAC_QUEUE 4   // decoded frames waiting to be handed out
#define AAC_FRAME_MAX (2048 * 8)   // samples in one decoded frame: 2048 per channel with SBR, 8 channels at most

struct OpaqueAudioConverter {
    AMediaCodec *codec;
    int rate, ch;                 // the stream as AudioConverterNew gave it; ch is also the output's channel count
    int out_ch;                   // the decoder's output channels (its output format)
    int64_t pts;                  // presentation time of the next input, in microseconds (MediaCodec wants one)
    int16_t *queue[AAC_QUEUE];    // decoded frames, already in ch channels
    UInt32 queue_frames[AAC_QUEUE];
    int queue_head, queue_n;
    int red_input, red_format;
};

// The AudioSpecificConfig in a magic cookie: an ES_Descriptor (tag 3) holding a DecoderConfigDescriptor (4) holding the DecoderSpecificInfo (5),
// a DecoderConfigDescriptor alone, or the AudioSpecificConfig itself (ISO/IEC 14496-1 7.2.6; the cookie hle_movie.c builds is the first kind)
static int aac_descriptor(const uint8_t **p, const uint8_t *end, int tag, size_t *len) {
    if (*p >= end || **p != tag) return 0;
    const uint8_t *q = *p + 1;
    size_t n = 0;
    for (int i = 0; i < 4; i++) {
        if (q >= end) return 0;
        uint8_t b = *q++;
        n = n << 7 | (b & 0x7f);
        if (!(b & 0x80)) break;
    }
    if ((size_t)(end - q) < n) return 0;
    *p = q; *len = n;
    return 1;
}
static int aac_cookie_asc(const uint8_t *cookie, size_t n, const uint8_t **asc, size_t *asc_n) {
    const uint8_t *p = cookie, *end = cookie + n;
    size_t len;
    if (n && cookie[0] == 3) {
        if (!aac_descriptor(&p, end, 3, &len) || len < 3) return 0;
        end = p + len;
        uint8_t flags = p[2];
        p += 3;   // ES_ID, then the flags
        if (flags & 0x80) p += 2;                       // dependsOn_ES_ID
        if (flags & 0x40) { if (p >= end) return 0; p += 1 + *p; }   // URL
        if (flags & 0x20) p += 2;                       // OCR_ES_Id
        if (p > end) return 0;
    }
    if (p < end && *p == 4) {
        if (!aac_descriptor(&p, end, 4, &len) || len < 13) return 0;
        end = p + len;
        p += 13;   // objectTypeIndication, streamType, bufferSizeDB, maxBitrate, avgBitrate
        if (!aac_descriptor(&p, end, 5, &len) || !len) return 0;
        *asc = p; *asc_n = len;
        return 1;
    }
    if (n < 2 || cookie[0] == 3) return 0;
    *asc = cookie; *asc_n = n;   // the AudioSpecificConfig alone
    return 1;
}

static int aac_start(AudioConverterRef c, const uint8_t *asc, size_t asc_n) {
    c->codec = AMediaCodec_createDecoderByType("audio/mp4a-latm");
    if (!c->codec) { LOG("[RED] AudioConverter: MediaCodec has no AAC decoder (audio/mp4a-latm): the AAC track is silent"); return 0; }
    AMediaFormat *fmt = AMediaFormat_new();
    AMediaFormat_setString(fmt, "mime", "audio/mp4a-latm");
    AMediaFormat_setInt32(fmt, "sample-rate", c->rate);
    AMediaFormat_setInt32(fmt, "channel-count", c->ch);
    AMediaFormat_setInt32(fmt, "is-adts", 0);
    AMediaFormat_setBuffer(fmt, "csd-0", asc, asc_n);
    media_status_t st = AMediaCodec_configure(c->codec, fmt, NULL, NULL, 0);
    AMediaFormat_delete(fmt);
    if (st == AMEDIA_OK) st = AMediaCodec_start(c->codec);
    if (st != AMEDIA_OK) {
        LOG("[RED] AudioConverter: MediaCodec's AAC decoder refused the stream (%d; %d channels %d Hz, AudioSpecificConfig %zu bytes, object type %d): the AAC track is silent",
            (int)st, c->ch, c->rate, asc_n, asc_n ? asc[0] >> 3 : 0);
        AMediaCodec_delete(c->codec);
        c->codec = NULL;
        return 0;
    }
    char *name = NULL;
    if (AMediaCodec_getName(c->codec, &name) == AMEDIA_OK && name) {
        LOG("[movie] AAC through MediaCodec (%s): %d channels %d Hz, object type %d", name, c->ch, c->rate, asc_n ? asc[0] >> 3 : 0);
        AMediaCodec_releaseName(c->codec, name);
    }
    return 1;
}

static void aac_mix(int16_t *dst, int dst_ch, const int16_t *src, int src_ch, UInt32 frames) {
    for (UInt32 f = 0; f < frames; f++, dst += dst_ch, src += src_ch) {
        if (dst_ch == src_ch) memcpy(dst, src, (size_t)dst_ch * 2);
        else if (dst_ch == 2 && src_ch == 1) dst[0] = dst[1] = src[0];
        else if (dst_ch == 1 && src_ch >= 2) dst[0] = (int16_t)(((int)src[0] + src[1]) / 2);
        else for (int k = 0; k < dst_ch; k++) dst[k] = k < src_ch ? src[k] : 0;
    }
}

// Take the decoder's outputs into the queue: wait up to timeout_us for the first, then take what is ready. 1 when a frame was queued.
static int aac_drain(AudioConverterRef c, int64_t timeout_us) {
    int got = 0;
    for (int tries = 0; tries < 8; tries++) {
        AMediaCodecBufferInfo info;
        ssize_t idx = AMediaCodec_dequeueOutputBuffer(c->codec, &info, got ? 0 : timeout_us);
        if (idx == AMEDIACODEC_INFO_OUTPUT_FORMAT_CHANGED) {
            AMediaFormat *f = AMediaCodec_getOutputFormat(c->codec);
            int32_t v;
            if (f) {
                if (AMediaFormat_getInt32(f, "channel-count", &v) && v > 0) c->out_ch = v;
                if (AMediaFormat_getInt32(f, "pcm-encoding", &v) && v != 2 && !c->red_format++)
                    LOG("[RED] AudioConverter: MediaCodec's AAC output is PCM encoding %d, not 16-bit: read as 16-bit", (int)v);
                if (AMediaFormat_getInt32(f, "sample-rate", &v) && v != c->rate)
                    LOG("[movie] AAC through MediaCodec: output %d Hz for a %d Hz stream (SBR doubles it), %d channels", (int)v, c->rate, c->out_ch);
                AMediaFormat_delete(f);
            }
            continue;
        }
        if (idx == AMEDIACODEC_INFO_OUTPUT_BUFFERS_CHANGED) continue;
        if (idx < 0) break;   // AMEDIACODEC_INFO_TRY_AGAIN_LATER, or an error
        size_t cap = 0;
        uint8_t *buf = AMediaCodec_getOutputBuffer(c->codec, (size_t)idx, &cap);
        int src_ch = c->out_ch > 0 ? c->out_ch : c->ch;
        UInt32 frames = buf && info.size > 0 && (size_t)info.offset + (size_t)info.size <= cap ? (UInt32)info.size / (UInt32)(2 * src_ch) : 0;
        if ((size_t)frames * (size_t)c->ch > AAC_FRAME_MAX) frames = (UInt32)(AAC_FRAME_MAX / c->ch);
        if (frames && c->queue_n < AAC_QUEUE) {
            int slot = (c->queue_head + c->queue_n) % AAC_QUEUE;
            aac_mix(c->queue[slot], c->ch, (const int16_t *)(buf + info.offset), src_ch, frames);
            c->queue_frames[slot] = frames;
            c->queue_n++;
            got = 1;
        } else if (frames && !c->red_input++) {
            LOG("[RED] AudioConverter: decoded AAC frames are not being taken (%d waiting): a frame is dropped", c->queue_n);
        }
        AMediaCodec_releaseOutputBuffer(c->codec, (size_t)idx, false);
    }
    return got;
}

OSStatus AudioConverterNew(const AudioStreamBasicDescription *in, const AudioStreamBasicDescription *out, AudioConverterRef *c) {
    if (c) *c = NULL;
    if (!in || !out || !c || in->mFormatID != kAudioFormatMPEG4AAC || out->mFormatID != kAudioFormatLinearPCM || out->mBitsPerChannel != 16
        || !(out->mFormatFlags & kLinearPCMFormatFlagIsSignedInteger) || out->mChannelsPerFrame < 1 || out->mChannelsPerFrame > 8) {
        static int once;
        if (!once++) said("AudioConverter other than MPEG-4 AAC to interleaved 16-bit PCM");
        return kStubFailed;
    }
    AudioConverterRef r = calloc(1, sizeof *r);
    if (!r) return kStubFailed;
    r->rate = in->mSampleRate > 0 ? (int)in->mSampleRate : 48000;
    r->ch = (int)out->mChannelsPerFrame;
    for (int i = 0; i < AAC_QUEUE; i++) {
        r->queue[i] = malloc(AAC_FRAME_MAX * sizeof(int16_t));
        if (!r->queue[i]) { AudioConverterDispose(r); return kStubFailed; }
    }
    *c = r;
    return noErr;
}

OSStatus AudioConverterDispose(AudioConverterRef c) {
    if (!c) return kStubFailed;
    if (c->codec) { AMediaCodec_stop(c->codec); AMediaCodec_delete(c->codec); }
    for (int i = 0; i < AAC_QUEUE; i++) free(c->queue[i]);
    free(c);
    return noErr;
}

OSStatus AudioConverterSetProperty(AudioConverterRef c, AudioConverterPropertyID id, UInt32 size, const void *data) {
    if (!c || id != kAudioConverterDecompressionMagicCookie || !data || !size) return kStubFailed;
    const uint8_t *asc = NULL;
    size_t asc_n = 0;
    if (!aac_cookie_asc(data, size, &asc, &asc_n)) { LOG("[RED] AudioConverter: no AudioSpecificConfig in the %u-byte magic cookie", (unsigned)size); return kStubFailed; }
    if (c->codec) { AMediaCodec_stop(c->codec); AMediaCodec_delete(c->codec); c->codec = NULL; }
    c->queue_n = 0;
    return aac_start(c, asc, asc_n) ? noErr : kStubFailed;
}

OSStatus AudioConverterFillComplexBuffer(AudioConverterRef c, AudioConverterComplexInputDataProc proc, void *ref, UInt32 *packets, AudioBufferList *out, AudioStreamPacketDescription *desc) {
    (void)desc;
    UInt32 capacity = packets ? *packets : 0;
    if (packets) *packets = 0;
    if (!c || !proc || !out || !out->mNumberBuffers || !out->mBuffers[0].mData) return kStubFailed;
    if (!c->codec) {   // no magic cookie: AAC-LC from the stream's rate and channel count, as hle_movie.c builds one without csd-0
        static const int rates[] = {96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350};
        int fi = 3;
        for (int i = 0; i < 13; i++) if (rates[i] == c->rate) fi = i;
        uint8_t asc[2] = {(uint8_t)(2 << 3 | fi >> 1), (uint8_t)((fi & 1) << 7 | (c->ch & 15) << 3)};
        if (!aac_start(c, asc, sizeof asc)) return kStubFailed;
    }
    UInt32 room = out->mBuffers[0].mDataByteSize / (UInt32)(2 * c->ch);
    if (capacity > room || !capacity) capacity = room;

    // One packet from the callback into the decoder
    UInt32 np = 1;
    AudioBufferList in = {1, {{(UInt32)c->ch, 0, NULL}}};
    AudioStreamPacketDescription *pd = NULL;
    OSStatus st = proc(c, &np, &in, &pd, ref);
    if (st == noErr && np > 0 && in.mBuffers[0].mData && in.mBuffers[0].mDataByteSize) {
        const uint8_t *pkt = in.mBuffers[0].mData;
        size_t n = pd ? pd->mDataByteSize : in.mBuffers[0].mDataByteSize;
        if (pd && pd->mStartOffset > 0) pkt += pd->mStartOffset;
        if (n > in.mBuffers[0].mDataByteSize) n = in.mBuffers[0].mDataByteSize;
        ssize_t idx = AMediaCodec_dequeueInputBuffer(c->codec, 10000);
        if (idx < 0) { aac_drain(c, 0); idx = AMediaCodec_dequeueInputBuffer(c->codec, 10000); }
        size_t cap = 0;
        uint8_t *buf = idx >= 0 ? AMediaCodec_getInputBuffer(c->codec, (size_t)idx, &cap) : NULL;
        if (buf && n <= cap) {
            memcpy(buf, pkt, n);
            AMediaCodec_queueInputBuffer(c->codec, (size_t)idx, 0, n, (uint64_t)c->pts, 0);
            c->pts += (int64_t)1024 * 1000000 / c->rate;
        } else {
            if (buf) AMediaCodec_queueInputBuffer(c->codec, (size_t)idx, 0, 0, (uint64_t)c->pts, 0);
            if (!c->red_input++) LOG("[RED] AudioConverter: MediaCodec took no AAC input (input buffer %zd, %zu of %zu bytes): a packet is dropped", idx, n, cap);
        }
        if (!c->queue_n) aac_drain(c, 5000);   // the decoder usually answers within one packet; wait a little for this packet's frame
        else aac_drain(c, 0);
        if (!c->queue_n) aac_drain(c, 15000);
        st = noErr;
    }

    // Hand out one decoded frame
    if (c->queue_n) {
        int slot = c->queue_head;
        UInt32 frames = c->queue_frames[slot] < capacity ? c->queue_frames[slot] : capacity;
        memcpy(out->mBuffers[0].mData, c->queue[slot], (size_t)frames * 2 * c->ch);
        out->mBuffers[0].mDataByteSize = frames * 2u * (UInt32)c->ch;
        c->queue_head = (c->queue_head + 1) % AAC_QUEUE;
        c->queue_n--;
        if (packets) *packets = frames;
    } else {
        out->mBuffers[0].mDataByteSize = 0;
    }
    return st;   // the callback's own status when it gave nothing (hle_movie.c ends a fill with 1), as AudioToolbox returns it
}

// ---- CoreFoundation, CoreMedia, CoreVideo, VideoToolbox: the H.264 decoder ----
const CFDictionaryKeyCallBacks kCFTypeDictionaryKeyCallBacks = {0, NULL, NULL, NULL, NULL, NULL};
const CFDictionaryValueCallBacks kCFTypeDictionaryValueCallBacks = {0, NULL, NULL, NULL, NULL};
const CMTime kCMTimeInvalid = {0, 0, 0, 0};
static const char k_pixel_format_key[] = "PixelFormatType";
const CFStringRef kCVPixelBufferPixelFormatTypeKey = (CFStringRef)k_pixel_format_key;

struct cf_base {
    void (*release)(void *);
};

void CFRelease(CFTypeRef cf) {
    if (!cf) return;
    const struct cf_base *b = (const struct cf_base *)cf;
    if (b->release) b->release((void *)cf);
    else free((void *)cf);
}

struct __CFNumber {
    struct cf_base base;
    int32_t val;
};

static void cf_number_release(void *p) { free(p); }

CFNumberRef CFNumberCreate(CFAllocatorRef a, CFNumberType type, const void *value) {
    (void)a; (void)type;
    struct __CFNumber *n = (struct __CFNumber *)calloc(1, sizeof(*n));
    if (!n) return NULL;
    n->base.release = cf_number_release;
    if (value) n->val = *(const int32_t *)value;
    return n;
}

struct __CFDictionary {
    struct cf_base base;
    int32_t pixel_format;
};

static void cf_dict_release(void *p) { free(p); }

CFDictionaryRef CFDictionaryCreate(CFAllocatorRef a, const void **keys, const void **values, CFIndex n, const CFDictionaryKeyCallBacks *kcb, const CFDictionaryValueCallBacks *vcb) {
    (void)a; (void)kcb; (void)vcb;
    struct __CFDictionary *d = (struct __CFDictionary *)calloc(1, sizeof(*d));
    if (!d) return NULL;
    d->base.release = cf_dict_release;
    d->pixel_format = kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange;
    for (CFIndex i = 0; i < n; i++) {
        if (keys && keys[i] == (const void *)kCVPixelBufferPixelFormatTypeKey && values && values[i]) {
            struct __CFNumber *num = (struct __CFNumber *)values[i];
            d->pixel_format = num->val;
        }
    }
    return d;
}

// Bit reader for parsing SPS width and height
typedef struct { const uint8_t *buf; size_t len; size_t bit_pos; } BitReader;
static inline uint32_t br_read_bit(BitReader *br) {
    if (br->bit_pos >= br->len * 8) return 0;
    uint32_t byte = br->buf[br->bit_pos / 8];
    uint32_t bit = (byte >> (7 - (br->bit_pos % 8))) & 1;
    br->bit_pos++;
    return bit;
}
static inline uint32_t br_read_bits(BitReader *br, int n) {
    uint32_t val = 0;
    for (int i = 0; i < n; i++) val = (val << 1) | br_read_bit(br);
    return val;
}
static inline uint32_t br_read_ue(BitReader *br) {
    int zeros = 0;
    while (br_read_bit(br) == 0 && zeros < 32 && br->bit_pos < br->len * 8) zeros++;
    if (zeros == 0) return 0;
    if (zeros >= 32) return 0;
    return (1u << zeros) - 1 + br_read_bits(br, zeros);
}
static inline int32_t br_read_se(BitReader *br) {
    uint32_t ue = br_read_ue(br);
    return (ue & 1) ? (int32_t)((ue + 1) / 2) : -(int32_t)(ue / 2);
}
static size_t unescape_rbsp(const uint8_t *src, size_t src_len, uint8_t *dst, size_t dst_len) {
    size_t d = 0;
    for (size_t i = 0; i < src_len && d < dst_len; i++) {
        if (i + 2 < src_len && src[i] == 0 && src[i + 1] == 0 && src[i + 2] == 3) {
            dst[d++] = src[i++];
            dst[d++] = src[i++];
        } else {
            dst[d++] = src[i];
        }
    }
    return d;
}
static void parse_sps_dimensions(const uint8_t *sps, size_t size, int32_t *w, int32_t *h) {
    *w = 512; *h = 608;
    if (size < 4) return;
    uint8_t rbsp[512];
    size_t rlen = unescape_rbsp(sps, size, rbsp, sizeof(rbsp));
    BitReader br = { rbsp, rlen, 0 };
    br_read_bits(&br, 8); // forbidden_zero_bit, nal_ref_idc, nal_unit_type
    uint32_t profile_idc = br_read_bits(&br, 8);
    br_read_bits(&br, 8); // constraint_set flags
    br_read_bits(&br, 8); // level_idc
    br_read_ue(&br); // seq_parameter_set_id
    if (profile_idc == 100 || profile_idc == 110 || profile_idc == 122 ||
        profile_idc == 244 || profile_idc == 44 || profile_idc == 83 ||
        profile_idc == 86 || profile_idc == 118 || profile_idc == 128 ||
        profile_idc == 138 || profile_idc == 139 || profile_idc == 134 || profile_idc == 135) {
        uint32_t chroma_format_idc = br_read_ue(&br);
        if (chroma_format_idc == 3) br_read_bit(&br);
        br_read_ue(&br); // bit_depth_luma_minus8
        br_read_ue(&br); // bit_depth_chroma_minus8
        br_read_bit(&br); // qpprime_y_zero_transform_bypass_flag
        uint32_t seq_scaling_matrix_present_flag = br_read_bit(&br);
        if (seq_scaling_matrix_present_flag) {
            int count = (chroma_format_idc != 3) ? 8 : 12;
            for (int i = 0; i < count; i++) {
                if (br_read_bit(&br)) {
                    int lastScale = 8, nextScale = 8;
                    int sizeOfScalingList = (i < 6) ? 16 : 64;
                    for (int j = 0; j < sizeOfScalingList; j++) {
                        if (nextScale != 0) {
                            int32_t delta_scale = br_read_se(&br);
                            nextScale = (lastScale + delta_scale + 256) % 256;
                        }
                        lastScale = (nextScale == 0) ? lastScale : nextScale;
                    }
                }
            }
        }
    }
    br_read_ue(&br); // log2_max_frame_num_minus4
    uint32_t pic_order_cnt_type = br_read_ue(&br);
    if (pic_order_cnt_type == 0) {
        br_read_ue(&br); // log2_max_pic_order_cnt_lsb_minus4
    } else if (pic_order_cnt_type == 1) {
        br_read_bit(&br); // delta_pic_order_always_zero_flag
        br_read_se(&br); // offset_for_non_ref_pic
        br_read_se(&br); // offset_for_top_to_bottom_field
        uint32_t num_ref = br_read_ue(&br);
        for (uint32_t i = 0; i < num_ref && i < 256; i++) br_read_se(&br);
    }
    br_read_ue(&br); // max_num_ref_frames
    br_read_bit(&br); // gaps_in_frame_num_value_allowed_flag
    uint32_t pic_width_in_mbs_minus1 = br_read_ue(&br);
    uint32_t pic_height_in_map_units_minus1 = br_read_ue(&br);
    uint32_t frame_mbs_only_flag = br_read_bit(&br);
    if (!frame_mbs_only_flag) br_read_bit(&br); // mb_adaptive_frame_field_flag
    br_read_bit(&br); // direct_8x8_inference_flag
    uint32_t frame_cropping_flag = br_read_bit(&br);
    uint32_t crop_left = 0, crop_right = 0, crop_top = 0, crop_bottom = 0;
    if (frame_cropping_flag) {
        crop_left = br_read_ue(&br);
        crop_right = br_read_ue(&br);
        crop_top = br_read_ue(&br);
        crop_bottom = br_read_ue(&br);
    }
    uint32_t width = (pic_width_in_mbs_minus1 + 1) * 16 - (crop_left + crop_right) * 2;
    uint32_t height = (2 - frame_mbs_only_flag) * (pic_height_in_map_units_minus1 + 1) * 16 - (crop_top + crop_bottom) * 2;
    if (width > 0 && width <= 4096 && height > 0 && height <= 4096) {
        *w = (int32_t)width;
        *h = (int32_t)height;
    }
}

struct OpaqueCMFormatDescription {
    struct cf_base base;
    int32_t width, height;
    uint8_t *sps; size_t sps_size;
    uint8_t *pps; size_t pps_size;
};

static void cm_format_desc_release(void *p) {
    struct OpaqueCMFormatDescription *fd = (struct OpaqueCMFormatDescription *)p;
    free(fd->sps);
    free(fd->pps);
    free(fd);
}

OSStatus CMVideoFormatDescriptionCreateFromH264ParameterSets(CFAllocatorRef a, size_t count, const uint8_t *const *sets, const size_t *sizes, int nal_len, CMVideoFormatDescriptionRef *out) {
    (void)a; (void)nal_len;
    if (!out) return kStubFailed;
    struct OpaqueCMFormatDescription *fd = (struct OpaqueCMFormatDescription *)calloc(1, sizeof(*fd));
    if (!fd) return kStubFailed;
    fd->base.release = cm_format_desc_release;
    fd->width = 512; fd->height = 608;
    if (count > 0 && sets && sizes && sets[0] && sizes[0] > 0) {
        fd->sps = (uint8_t *)malloc(sizes[0]);
        if (fd->sps) {
            memcpy(fd->sps, sets[0], sizes[0]);
            fd->sps_size = sizes[0];
            parse_sps_dimensions(fd->sps, fd->sps_size, &fd->width, &fd->height);
        }
    }
    if (count > 1 && sets && sizes && sets[1] && sizes[1] > 0) {
        fd->pps = (uint8_t *)malloc(sizes[1]);
        if (fd->pps) {
            memcpy(fd->pps, sets[1], sizes[1]);
            fd->pps_size = sizes[1];
        }
    }
    *out = fd;
    return noErr;
}

CMVideoDimensions CMVideoFormatDescriptionGetDimensions(CMVideoFormatDescriptionRef d) {
    CMVideoDimensions dims = {0, 0};
    if (d) {
        dims.width = d->width;
        dims.height = d->height;
    }
    return dims;
}

struct OpaqueCMBlockBuffer {
    struct cf_base base;
    uint8_t *data;
    size_t size;
};

static void cm_block_buffer_release(void *p) {
    struct OpaqueCMBlockBuffer *bb = (struct OpaqueCMBlockBuffer *)p;
    free(bb->data);
    free(bb);
}

OSStatus CMBlockBufferCreateWithMemoryBlock(CFAllocatorRef a, void *block, size_t len, CFAllocatorRef ba, const void *source, size_t off, size_t dlen, uint32_t flags, CMBlockBufferRef *out) {
    (void)a; (void)block; (void)ba; (void)source; (void)off; (void)dlen; (void)flags;
    if (!out) return kStubFailed;
    struct OpaqueCMBlockBuffer *bb = (struct OpaqueCMBlockBuffer *)calloc(1, sizeof(*bb));
    if (!bb) return kStubFailed;
    bb->base.release = cm_block_buffer_release;
    bb->size = len;
    bb->data = (uint8_t *)malloc(len ? len : 1);
    *out = bb;
    return noErr;
}

OSStatus CMBlockBufferReplaceDataBytes(const void *src, CMBlockBufferRef b, size_t off, size_t len) {
    if (!b || !b->data || !src || off + len > b->size) return kStubFailed;
    memcpy(b->data + off, src, len);
    return noErr;
}

struct OpaqueCMSampleBuffer {
    struct cf_base base;
    CMBlockBufferRef bb;
    CMTime pts;
};

static void cm_sample_buffer_release(void *p) {
    free(p);
}

OSStatus CMSampleBufferCreateReady(CFAllocatorRef a, CMBlockBufferRef data, CMVideoFormatDescriptionRef fd, CFIndex nsamples, CFIndex ntiming, const CMSampleTimingInfo *timing, CFIndex nsizes, const size_t *sizes, CMSampleBufferRef *out) {
    (void)a; (void)fd; (void)nsamples; (void)nsizes; (void)sizes;
    if (!out) return kStubFailed;
    struct OpaqueCMSampleBuffer *sb = (struct OpaqueCMSampleBuffer *)calloc(1, sizeof(*sb));
    if (!sb) return kStubFailed;
    sb->base.release = cm_sample_buffer_release;
    sb->bb = data;
    if (ntiming > 0 && timing) {
        sb->pts = timing[0].presentationTimeStamp;
    } else {
        sb->pts = kCMTimeInvalid;
    }
    *out = sb;
    return noErr;
}

struct __CVBuffer {
    struct cf_base base;
    _Atomic int refcount;
    int32_t format;
    size_t width, height;
    size_t stride_y, stride_uv;
    uint8_t *y_plane, *uv_plane;
    uint8_t *rgba_data;
    uint8_t *buf_storage;
};

CVPixelBufferRef CVPixelBufferRetain(CVPixelBufferRef b) {
    if (b) atomic_fetch_add(&b->refcount, 1);
    return b;
}

void CVPixelBufferRelease(CVPixelBufferRef b) {
    if (!b) return;
    if (atomic_fetch_sub(&b->refcount, 1) == 1) {
        free(b->buf_storage);
        free(b);
    }
}

CVReturn CVPixelBufferLockBaseAddress(CVPixelBufferRef b, CVPixelBufferLockFlags f) { (void)b; (void)f; return 0; }
CVReturn CVPixelBufferUnlockBaseAddress(CVPixelBufferRef b, CVPixelBufferLockFlags f) { (void)b; (void)f; return 0; }
size_t CVPixelBufferGetWidth(CVPixelBufferRef b) { return b ? b->width : 0; }
size_t CVPixelBufferGetHeight(CVPixelBufferRef b) { return b ? b->height : 0; }
void *CVPixelBufferGetBaseAddress(CVPixelBufferRef b) { return b ? (b->rgba_data ? (void *)b->rgba_data : (void *)b->y_plane) : NULL; }
size_t CVPixelBufferGetBytesPerRow(CVPixelBufferRef b) { return b ? (b->rgba_data ? b->width * 4 : b->stride_y) : 0; }
size_t CVPixelBufferGetWidthOfPlane(CVPixelBufferRef b, size_t plane) {
    if (!b) return 0;
    return (plane == 0) ? b->width : (plane == 1 ? (b->width + 1) / 2 : 0);
}
size_t CVPixelBufferGetHeightOfPlane(CVPixelBufferRef b, size_t plane) {
    if (!b) return 0;
    return (plane == 0) ? b->height : (plane == 1 ? (b->height + 1) / 2 : 0);
}
void *CVPixelBufferGetBaseAddressOfPlane(CVPixelBufferRef b, size_t plane) {
    if (!b) return NULL;
    return (plane == 0) ? (void *)b->y_plane : (plane == 1 ? (void *)b->uv_plane : NULL);
}
size_t CVPixelBufferGetBytesPerRowOfPlane(CVPixelBufferRef b, size_t plane) {
    if (!b) return 0;
    return (plane == 0) ? b->stride_y : (plane == 1 ? b->stride_uv : 0);
}

static CVPixelBufferRef cv_pixel_buffer_create_nv12(int w, int h, int stride, int slice_h, const uint8_t *src) {
    struct __CVBuffer *b = (struct __CVBuffer *)calloc(1, sizeof(*b));
    if (!b) return NULL;
    b->base.release = (void (*)(void *))CVPixelBufferRelease;
    atomic_init(&b->refcount, 1);
    b->format = kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange;
    b->width = w;
    b->height = h;
    b->stride_y = stride;
    b->stride_uv = stride;
    size_t y_sz = (size_t)stride * slice_h;
    size_t uv_sz = (size_t)stride * ((slice_h + 1) / 2);
    b->buf_storage = (uint8_t *)malloc(y_sz + uv_sz);
    if (b->buf_storage) {
        if (src) memcpy(b->buf_storage, src, y_sz + uv_sz);
        b->y_plane = b->buf_storage;
        b->uv_plane = b->buf_storage + y_sz;
    }
    return b;
}

static CVPixelBufferRef cv_pixel_buffer_create_nv12_dummy(int w, int h) {
    struct __CVBuffer *b = (struct __CVBuffer *)calloc(1, sizeof(*b));
    if (!b) return NULL;
    b->base.release = (void (*)(void *))CVPixelBufferRelease;
    atomic_init(&b->refcount, 1);
    b->format = kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange;
    b->width = w > 0 ? w : 512;
    b->height = h > 0 ? h : 608;
    b->stride_y = b->width;
    b->stride_uv = b->width;
    size_t y_sz = b->width * b->height;
    size_t uv_sz = b->width * ((b->height + 1) / 2);
    b->buf_storage = (uint8_t *)malloc(y_sz + uv_sz);
    if (b->buf_storage) {
        memset(b->buf_storage, 16, y_sz);          // video-range black Y
        memset(b->buf_storage + y_sz, 128, uv_sz); // chroma neutral UV
        b->y_plane = b->buf_storage;
        b->uv_plane = b->buf_storage + y_sz;
    }
    return b;
}

struct OpaqueVTDecompressionSession {
    struct cf_base base;
    CMVideoFormatDescriptionRef fd;
    VTDecompressionOutputCallbackRecord cb;
    int32_t pixel_format;
    int32_t width, height;
    AMediaCodec *codec;
    CVPixelBufferRef last_pb;
};

static void vt_decompression_session_release(void *p) {
    struct OpaqueVTDecompressionSession *s = (struct OpaqueVTDecompressionSession *)p;
    if (s->codec) {
        AMediaCodec_stop(s->codec);
        AMediaCodec_delete(s->codec);
        s->codec = NULL;
    }
    if (s->last_pb) {
        CVPixelBufferRelease(s->last_pb);
        s->last_pb = NULL;
    }
    free(s);
}

OSStatus VTDecompressionSessionCreate(CFAllocatorRef a, CMVideoFormatDescriptionRef fd, CFDictionaryRef spec, CFDictionaryRef attrs, const VTDecompressionOutputCallbackRecord *cb, VTDecompressionSessionRef *out) {
    (void)a; (void)spec;
    if (!out) return kStubFailed;
    struct OpaqueVTDecompressionSession *s = (struct OpaqueVTDecompressionSession *)calloc(1, sizeof(*s));
    if (!s) return kStubFailed;
    s->base.release = vt_decompression_session_release;
    s->fd = fd;
    if (cb) s->cb = *cb;
    s->pixel_format = kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange;
    if (attrs) {
        struct __CFDictionary *d = (struct __CFDictionary *)attrs;
        s->pixel_format = d->pixel_format;
    }
    if (fd) {
        s->width = fd->width;
        s->height = fd->height;
    }
    if (s->width <= 0) s->width = 512;
    if (s->height <= 0) s->height = 608;

    s->codec = AMediaCodec_createDecoderByType("video/avc");
    if (s->codec) {
        AMediaFormat *fmt = AMediaFormat_new();
        AMediaFormat_setString(fmt, "mime", "video/avc");
        AMediaFormat_setInt32(fmt, "width", s->width);
        AMediaFormat_setInt32(fmt, "height", s->height);
        if (fd && fd->sps && fd->sps_size > 0) {
            uint8_t csd0[516];
            csd0[0] = 0; csd0[1] = 0; csd0[2] = 0; csd0[3] = 1;
            size_t csd0_len = fd->sps_size;
            if (csd0_len > sizeof(csd0) - 4) csd0_len = sizeof(csd0) - 4;
            memcpy(csd0 + 4, fd->sps, csd0_len);
            AMediaFormat_setBuffer(fmt, "csd-0", csd0, csd0_len + 4);
        }
        if (fd && fd->pps && fd->pps_size > 0) {
            uint8_t csd1[516];
            csd1[0] = 0; csd1[1] = 0; csd1[2] = 0; csd1[3] = 1;
            size_t csd1_len = fd->pps_size;
            if (csd1_len > sizeof(csd1) - 4) csd1_len = sizeof(csd1) - 4;
            memcpy(csd1 + 4, fd->pps, csd1_len);
            AMediaFormat_setBuffer(fmt, "csd-1", csd1, csd1_len + 4);
        }
        media_status_t st = AMediaCodec_configure(s->codec, fmt, NULL, NULL, 0);
        AMediaFormat_delete(fmt);
        if (st == AMEDIA_OK) {
            st = AMediaCodec_start(s->codec);
            if (st != AMEDIA_OK) {
                LOG("[RED] AMediaCodec_start failed (%d)", st);
                AMediaCodec_delete(s->codec);
                s->codec = NULL;
            } else {
                LOG("[movie] AMediaCodec AVC decoder started successfully (%dx%d)", s->width, s->height);
            }
        } else {
            LOG("[RED] AMediaCodec_configure failed (%d)", st);
            AMediaCodec_delete(s->codec);
            s->codec = NULL;
        }
    } else {
        LOG("[RED] AMediaCodec_createDecoderByType(video/avc) failed");
    }

    *out = s;
    return noErr;
}

OSStatus VTDecompressionSessionDecodeFrame(VTDecompressionSessionRef s, CMSampleBufferRef sb, VTDecodeFrameFlags flags, void *ref, VTDecodeInfoFlags *info) {
    (void)flags;
    if (info) *info = 0;
    if (!s || !sb || !sb->bb) return kStubFailed;

    if (s->codec && sb->bb->size > 0) {
        uint8_t *in_data = (uint8_t *)malloc(sb->bb->size);
        if (in_data) {
            memcpy(in_data, sb->bb->data, sb->bb->size);
            size_t off = 0;
            while (off + 4 <= sb->bb->size) {
                uint32_t nlen = ((uint32_t)in_data[off] << 24) |
                                ((uint32_t)in_data[off + 1] << 16) |
                                ((uint32_t)in_data[off + 2] << 8) |
                                ((uint32_t)in_data[off + 3]);
                in_data[off] = 0;
                in_data[off + 1] = 0;
                in_data[off + 2] = 0;
                in_data[off + 3] = 1;
                if (nlen == 0 || off + 4 + nlen > sb->bb->size) break;
                off += 4 + nlen;
            }

            ssize_t inIdx = AMediaCodec_dequeueInputBuffer(s->codec, 2000);
            if (inIdx >= 0) {
                size_t bufSize = 0;
                uint8_t *buf = AMediaCodec_getInputBuffer(s->codec, (size_t)inIdx, &bufSize);
                if (buf && bufSize >= sb->bb->size) {
                    memcpy(buf, in_data, sb->bb->size);
                    int64_t pts = sb->pts.timescale ? (sb->pts.value * 1000000 / sb->pts.timescale) : 0;
                    AMediaCodec_queueInputBuffer(s->codec, (size_t)inIdx, 0, sb->bb->size, (uint64_t)pts, 0);
                } else {
                    AMediaCodec_queueInputBuffer(s->codec, (size_t)inIdx, 0, 0, 0, 0);
                }
            }
            free(in_data);
        }

        AMediaCodecBufferInfo binfo;
        ssize_t outIdx = AMediaCodec_dequeueOutputBuffer(s->codec, &binfo, 2000);
        if (outIdx == AMEDIACODEC_INFO_OUTPUT_FORMAT_CHANGED) {
            AMediaFormat *outFmt = AMediaCodec_getOutputFormat(s->codec);
            if (outFmt) {
                int32_t val = 0;
                if (AMediaFormat_getInt32(outFmt, "width", &val) && val > 0) s->width = val;
                if (AMediaFormat_getInt32(outFmt, "height", &val) && val > 0) s->height = val;
                AMediaFormat_delete(outFmt);
            }
            outIdx = AMediaCodec_dequeueOutputBuffer(s->codec, &binfo, 2000);
        }
        if (outIdx >= 0) {
            size_t outBufSize = 0;
            uint8_t *outBuf = AMediaCodec_getOutputBuffer(s->codec, (size_t)outIdx, &outBufSize);
            if (outBuf) {
                AMediaFormat *outFmt = AMediaCodec_getOutputFormat(s->codec);
                int32_t fw = s->width, fh = s->height, stride = s->width, slice_h = s->height;
                if (outFmt) {
                    int32_t val = 0;
                    if (AMediaFormat_getInt32(outFmt, "width", &val) && val > 0) fw = val;
                    if (AMediaFormat_getInt32(outFmt, "height", &val) && val > 0) fh = val;
                    if (AMediaFormat_getInt32(outFmt, "stride", &val) && val > 0) stride = val;
                    if (AMediaFormat_getInt32(outFmt, "slice-height", &val) && val > 0) slice_h = val;
                    AMediaFormat_delete(outFmt);
                }
                if (stride < fw) stride = fw;
                if (slice_h < fh) slice_h = fh;

                if (s->last_pb) CVPixelBufferRelease(s->last_pb);
                s->last_pb = cv_pixel_buffer_create_nv12(fw, fh, stride, slice_h, outBuf + binfo.offset);
            }
            AMediaCodec_releaseOutputBuffer(s->codec, (size_t)outIdx, false);
        }
    }

    CVPixelBufferRef pb = NULL;
    if (s->last_pb) {
        pb = CVPixelBufferRetain(s->last_pb);
    } else {
        pb = cv_pixel_buffer_create_nv12_dummy(s->width, s->height);
    }

    if (s->cb.decompressionOutputCallback) {
        s->cb.decompressionOutputCallback(s->cb.decompressionOutputRefCon, ref, noErr, 0, pb, sb->pts, kCMTimeInvalid);
    }
    CVPixelBufferRelease(pb);

    return noErr;
}

OSStatus VTDecompressionSessionWaitForAsynchronousFrames(VTDecompressionSessionRef s) {
    (void)s;
    return noErr;
}

void VTDecompressionSessionInvalidate(VTDecompressionSessionRef s) {
    if (!s) return;
    if (s->codec) {
        AMediaCodec_stop(s->codec);
        AMediaCodec_delete(s->codec);
        s->codec = NULL;
    }
}
