// The Apple media frameworks the host names, on bionic. Two families have real backends: the AudioUnit
// output plays through AAudio (hle_audio.c's 48 kHz stereo PCM) and VideoToolbox's H.264 decoder decodes
// through MediaCodec into an NV12 CVPixelBufferRef (hle_movie_avc.c). The rest fail, each family saying so
// once with a [RED] line, so that the Android link set is complete: an AAC track through AudioConverter is
// silent, an unsupported AudioUnit component type is refused. The host's own fallbacks then apply: the
// silent sink paces the game's audio in real time.
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

// ---- AudioToolbox: output units (AAudio) and the AAC converter ----
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
OSStatus AudioConverterNew(const AudioStreamBasicDescription *in, const AudioStreamBasicDescription *out, AudioConverterRef *c) { (void)in; (void)out; if (c) *c = NULL; static int once; if (!once++) said("AAC decoding through AudioToolbox"); return kStubFailed; }
OSStatus AudioConverterDispose(AudioConverterRef c) { (void)c; return kStubFailed; }
OSStatus AudioConverterSetProperty(AudioConverterRef c, AudioConverterPropertyID id, UInt32 size, const void *data) { (void)c; (void)id; (void)size; (void)data; return kStubFailed; }
OSStatus AudioConverterFillComplexBuffer(AudioConverterRef c, AudioConverterComplexInputDataProc proc, void *ref, UInt32 *packets, AudioBufferList *out, AudioStreamPacketDescription *desc) {
    (void)c; (void)proc; (void)ref; (void)out; (void)desc; if (packets) *packets = 0; return kStubFailed;
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
