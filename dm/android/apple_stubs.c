// The Apple media frameworks the host names, on bionic: every function fails, and each family says so once with a [RED] line. These are interfaces only, so that the Android
// link set is complete; the backends (an AAudio output for hle_audio.c, MediaCodec for hle_movie.c's AAC and hle_movie_avc.c's H.264) are separate work. The host's own fallbacks
// then apply: the silent sink paces the game's audio in real time, an AAC track is silent, an AVC movie shows black frames.
#include "../host/dm.h"   // LOG
#include <AudioToolbox/AudioToolbox.h>
#include <VideoToolbox/VideoToolbox.h>

enum { kStubFailed = -50 /* paramErr: no component, converter or session exists on this platform */ };
static void said(const char *what) { LOG("[RED] %s is not implemented on this platform: the Apple framework calls fail here (interface stubs, dm/android/apple_stubs.c)", what); }

// ---- AudioToolbox: output units and the AAC converter ----
AudioComponent AudioComponentFindNext(AudioComponent after, const AudioComponentDescription *desc) { (void)after; (void)desc; static int once; if (!once++) said("audio output through an AudioUnit"); return NULL; }
OSStatus AudioComponentInstanceNew(AudioComponent c, AudioComponentInstance *out) { (void)c; if (out) *out = NULL; return kStubFailed; }
OSStatus AudioComponentInstanceDispose(AudioComponentInstance i) { (void)i; return kStubFailed; }
OSStatus AudioUnitInitialize(AudioUnit u) { (void)u; return kStubFailed; }
OSStatus AudioUnitUninitialize(AudioUnit u) { (void)u; return kStubFailed; }
OSStatus AudioUnitSetProperty(AudioUnit u, AudioUnitPropertyID id, AudioUnitScope scope, AudioUnitElement el, const void *data, UInt32 size) { (void)u; (void)id; (void)scope; (void)el; (void)data; (void)size; return kStubFailed; }
OSStatus AudioUnitGetProperty(AudioUnit u, AudioUnitPropertyID id, AudioUnitScope scope, AudioUnitElement el, void *data, UInt32 *size) { (void)u; (void)id; (void)scope; (void)el; (void)data; (void)size; return kStubFailed; }
OSStatus AudioOutputUnitStart(AudioUnit u) { (void)u; return kStubFailed; }
OSStatus AudioOutputUnitStop(AudioUnit u) { (void)u; return kStubFailed; }
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
void CFRelease(CFTypeRef cf) { (void)cf; }   // nothing made here is ever handed out, so there is nothing to release
CFNumberRef CFNumberCreate(CFAllocatorRef a, CFNumberType type, const void *value) { (void)a; (void)type; (void)value; return NULL; }
CFDictionaryRef CFDictionaryCreate(CFAllocatorRef a, const void **keys, const void **values, CFIndex n, const CFDictionaryKeyCallBacks *kcb, const CFDictionaryValueCallBacks *vcb) { (void)a; (void)keys; (void)values; (void)n; (void)kcb; (void)vcb; return NULL; }
OSStatus CMVideoFormatDescriptionCreateFromH264ParameterSets(CFAllocatorRef a, size_t count, const uint8_t *const *sets, const size_t *sizes, int nal_len, CMVideoFormatDescriptionRef *out) {
    (void)a; (void)count; (void)sets; (void)sizes; (void)nal_len; if (out) *out = NULL; static int once; if (!once++) said("H.264 decoding through VideoToolbox"); return kStubFailed;
}
CMVideoDimensions CMVideoFormatDescriptionGetDimensions(CMVideoFormatDescriptionRef d) { (void)d; CMVideoDimensions z = {0, 0}; return z; }
OSStatus CMBlockBufferCreateWithMemoryBlock(CFAllocatorRef a, void *block, size_t len, CFAllocatorRef ba, const void *source, size_t off, size_t dlen, uint32_t flags, CMBlockBufferRef *out) {
    (void)a; (void)block; (void)len; (void)ba; (void)source; (void)off; (void)dlen; (void)flags; if (out) *out = NULL; return kStubFailed;
}
OSStatus CMBlockBufferReplaceDataBytes(const void *src, CMBlockBufferRef b, size_t off, size_t len) { (void)src; (void)b; (void)off; (void)len; return kStubFailed; }
OSStatus CMSampleBufferCreateReady(CFAllocatorRef a, CMBlockBufferRef data, CMVideoFormatDescriptionRef fd, CFIndex nsamples, CFIndex ntiming, const CMSampleTimingInfo *timing, CFIndex nsizes, const size_t *sizes, CMSampleBufferRef *out) {
    (void)a; (void)data; (void)fd; (void)nsamples; (void)ntiming; (void)timing; (void)nsizes; (void)sizes; if (out) *out = NULL; return kStubFailed;
}
OSStatus VTDecompressionSessionCreate(CFAllocatorRef a, CMVideoFormatDescriptionRef fd, CFDictionaryRef spec, CFDictionaryRef attrs, const VTDecompressionOutputCallbackRecord *cb, VTDecompressionSessionRef *out) {
    (void)a; (void)fd; (void)spec; (void)attrs; (void)cb; if (out) *out = NULL; return kStubFailed;
}
OSStatus VTDecompressionSessionDecodeFrame(VTDecompressionSessionRef s, CMSampleBufferRef sb, VTDecodeFrameFlags flags, void *ref, VTDecodeInfoFlags *info) { (void)s; (void)sb; (void)flags; (void)ref; if (info) *info = 0; return kStubFailed; }
OSStatus VTDecompressionSessionWaitForAsynchronousFrames(VTDecompressionSessionRef s) { (void)s; return kStubFailed; }
void VTDecompressionSessionInvalidate(VTDecompressionSessionRef s) { (void)s; }
CVPixelBufferRef CVPixelBufferRetain(CVPixelBufferRef b) { return b; }
void CVPixelBufferRelease(CVPixelBufferRef b) { (void)b; }
CVReturn CVPixelBufferLockBaseAddress(CVPixelBufferRef b, CVPixelBufferLockFlags f) { (void)b; (void)f; return -1; }
CVReturn CVPixelBufferUnlockBaseAddress(CVPixelBufferRef b, CVPixelBufferLockFlags f) { (void)b; (void)f; return -1; }
size_t CVPixelBufferGetWidth(CVPixelBufferRef b) { (void)b; return 0; }
size_t CVPixelBufferGetHeight(CVPixelBufferRef b) { (void)b; return 0; }
void *CVPixelBufferGetBaseAddress(CVPixelBufferRef b) { (void)b; return NULL; }
size_t CVPixelBufferGetBytesPerRow(CVPixelBufferRef b) { (void)b; return 0; }
size_t CVPixelBufferGetWidthOfPlane(CVPixelBufferRef b, size_t plane) { (void)b; (void)plane; return 0; }
size_t CVPixelBufferGetHeightOfPlane(CVPixelBufferRef b, size_t plane) { (void)b; (void)plane; return 0; }
void *CVPixelBufferGetBaseAddressOfPlane(CVPixelBufferRef b, size_t plane) { (void)b; (void)plane; return NULL; }
size_t CVPixelBufferGetBytesPerRowOfPlane(CVPixelBufferRef b, size_t plane) { (void)b; (void)plane; return 0; }
