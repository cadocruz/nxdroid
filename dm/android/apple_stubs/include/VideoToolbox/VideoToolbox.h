// The VideoToolbox, CoreMedia, CoreVideo and CoreFoundation interface the host names (hle_movie_avc.c's H.264 decoder), on bionic: the types and constants, and functions
// that fail with a [RED] line once (dm/android/apple_stubs.c). No video backend is behind them: an AVC movie plays black frames on this platform (the decoder's own fallback)
// until a MediaCodec path exists. This directory is on the Android include path only; the Apple build sees the real frameworks.
#pragma once
#include <stdint.h>
#include <stddef.h>
typedef int32_t OSStatus; typedef uint32_t UInt32; typedef int32_t SInt32;
typedef const void *CFTypeRef; typedef const void *CFAllocatorRef; typedef struct __CFNumber *CFNumberRef; typedef struct __CFDictionary *CFDictionaryRef; typedef struct __CFString *CFStringRef;
typedef long CFIndex; typedef CFIndex CFNumberType;
typedef struct { CFIndex version; const void *retain, *release, *copyDescription, *equal, *hash; } CFDictionaryKeyCallBacks;
typedef struct { CFIndex version; const void *retain, *release, *copyDescription, *equal; } CFDictionaryValueCallBacks;
extern const CFDictionaryKeyCallBacks kCFTypeDictionaryKeyCallBacks;
extern const CFDictionaryValueCallBacks kCFTypeDictionaryValueCallBacks;
enum { kCFNumberSInt32Type = 3 };
void CFRelease(CFTypeRef cf);
CFNumberRef CFNumberCreate(CFAllocatorRef a, CFNumberType type, const void *value);
CFDictionaryRef CFDictionaryCreate(CFAllocatorRef a, const void **keys, const void **values, CFIndex n, const CFDictionaryKeyCallBacks *kcb, const CFDictionaryValueCallBacks *vcb);

typedef struct { int64_t value; int32_t timescale; uint32_t flags; int64_t epoch; } CMTime;
extern const CMTime kCMTimeInvalid;
static inline CMTime CMTimeMake(int64_t value, int32_t timescale) { CMTime t = {value, timescale, 1u, 0}; return t; }
typedef struct { CMTime duration, presentationTimeStamp, decodeTimeStamp; } CMSampleTimingInfo;
typedef struct { int32_t width, height; } CMVideoDimensions;
typedef struct OpaqueCMFormatDescription *CMVideoFormatDescriptionRef;
typedef struct OpaqueCMBlockBuffer *CMBlockBufferRef;
typedef struct OpaqueCMSampleBuffer *CMSampleBufferRef;
typedef struct __CVBuffer *CVPixelBufferRef; typedef CVPixelBufferRef CVImageBufferRef;
typedef struct OpaqueVTDecompressionSession *VTDecompressionSessionRef;
typedef UInt32 VTDecodeInfoFlags, VTDecodeFrameFlags, CVPixelBufferLockFlags; typedef int32_t CVReturn;
typedef void (*VTDecompressionOutputCallback)(void *ref, void *src, OSStatus st, VTDecodeInfoFlags flags, CVImageBufferRef img, CMTime pts, CMTime dur);
typedef struct { VTDecompressionOutputCallback decompressionOutputCallback; void *decompressionOutputRefCon; } VTDecompressionOutputCallbackRecord;
enum { kCVPixelFormatType_32BGRA = 0x42475241 /* 'BGRA' */, kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange = 0x34323076 /* '420v' */, kCVPixelBufferLock_ReadOnly = 1 };
extern const CFStringRef kCVPixelBufferPixelFormatTypeKey;
OSStatus CMVideoFormatDescriptionCreateFromH264ParameterSets(CFAllocatorRef a, size_t count, const uint8_t *const *sets, const size_t *sizes, int nal_len, CMVideoFormatDescriptionRef *out);
CMVideoDimensions CMVideoFormatDescriptionGetDimensions(CMVideoFormatDescriptionRef d);
OSStatus CMBlockBufferCreateWithMemoryBlock(CFAllocatorRef a, void *block, size_t len, CFAllocatorRef ba, const void *source, size_t off, size_t dlen, uint32_t flags, CMBlockBufferRef *out);
OSStatus CMBlockBufferReplaceDataBytes(const void *src, CMBlockBufferRef b, size_t off, size_t len);
OSStatus CMSampleBufferCreateReady(CFAllocatorRef a, CMBlockBufferRef data, CMVideoFormatDescriptionRef fd, CFIndex nsamples, CFIndex ntiming, const CMSampleTimingInfo *timing, CFIndex nsizes, const size_t *sizes, CMSampleBufferRef *out);
OSStatus VTDecompressionSessionCreate(CFAllocatorRef a, CMVideoFormatDescriptionRef fd, CFDictionaryRef spec, CFDictionaryRef attrs, const VTDecompressionOutputCallbackRecord *cb, VTDecompressionSessionRef *out);
OSStatus VTDecompressionSessionDecodeFrame(VTDecompressionSessionRef s, CMSampleBufferRef sb, VTDecodeFrameFlags flags, void *ref, VTDecodeInfoFlags *info);
OSStatus VTDecompressionSessionWaitForAsynchronousFrames(VTDecompressionSessionRef s);
void VTDecompressionSessionInvalidate(VTDecompressionSessionRef s);
CVPixelBufferRef CVPixelBufferRetain(CVPixelBufferRef b);
void CVPixelBufferRelease(CVPixelBufferRef b);
CVReturn CVPixelBufferLockBaseAddress(CVPixelBufferRef b, CVPixelBufferLockFlags f);
CVReturn CVPixelBufferUnlockBaseAddress(CVPixelBufferRef b, CVPixelBufferLockFlags f);
size_t CVPixelBufferGetWidth(CVPixelBufferRef b);
size_t CVPixelBufferGetHeight(CVPixelBufferRef b);
void *CVPixelBufferGetBaseAddress(CVPixelBufferRef b);
size_t CVPixelBufferGetBytesPerRow(CVPixelBufferRef b);
size_t CVPixelBufferGetWidthOfPlane(CVPixelBufferRef b, size_t plane);
size_t CVPixelBufferGetHeightOfPlane(CVPixelBufferRef b, size_t plane);
void *CVPixelBufferGetBaseAddressOfPlane(CVPixelBufferRef b, size_t plane);
size_t CVPixelBufferGetBytesPerRowOfPlane(CVPixelBufferRef b, size_t plane);
