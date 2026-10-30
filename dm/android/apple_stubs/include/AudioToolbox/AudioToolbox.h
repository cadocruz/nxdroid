// The AudioToolbox interface the host names (hle_audio.c's output unit, hle_movie.c's AAC converter), on bionic: the types and constants, and functions that fail with a
// [RED] line once (dm/android/apple_stubs.c). No audio backend is behind them: hle_audio.c's silent sink is the output on this platform (DM_AUDIO is off by default here),
// and an AAC movie track is silent. This directory is on the Android include path only; the Apple build sees the real framework.
#pragma once
#include <stdint.h>
#include <stddef.h>
typedef int32_t OSStatus; typedef uint32_t UInt32; typedef int32_t SInt32; typedef double Float64; typedef uint8_t Boolean;
typedef struct { Float64 mSampleRate; UInt32 mFormatID, mFormatFlags, mBytesPerPacket, mFramesPerPacket, mBytesPerFrame, mChannelsPerFrame, mBitsPerChannel, mReserved; } AudioStreamBasicDescription;
typedef struct { UInt32 mNumberChannels, mDataByteSize; void *mData; } AudioBuffer;
typedef struct { UInt32 mNumberBuffers; AudioBuffer mBuffers[1]; } AudioBufferList;
typedef struct { int64_t mStartOffset; UInt32 mVariableFramesInPacket, mDataByteSize; } AudioStreamPacketDescription;
typedef struct { Float64 mSampleTime; uint64_t mHostTime; Float64 mRateScalar; uint64_t mWordClockTime; uint8_t mSMPTETime[24]; UInt32 mFlags, mReserved; } AudioTimeStamp;
typedef UInt32 AudioUnitRenderActionFlags, AudioUnitPropertyID, AudioUnitScope, AudioUnitElement, AudioConverterPropertyID;
typedef struct OpaqueAudioComponent *AudioComponent;
typedef struct OpaqueAudioComponentInstance *AudioComponentInstance;
typedef AudioComponentInstance AudioUnit;
typedef struct OpaqueAudioConverter *AudioConverterRef;
typedef struct { UInt32 componentType, componentSubType, componentManufacturer, componentFlags, componentFlagsMask; } AudioComponentDescription;
typedef OSStatus (*AURenderCallback)(void *ref, AudioUnitRenderActionFlags *flags, const AudioTimeStamp *ts, UInt32 bus, UInt32 frames, AudioBufferList *data);
typedef struct { AURenderCallback inputProc; void *inputProcRefCon; } AURenderCallbackStruct;
typedef OSStatus (*AudioConverterComplexInputDataProc)(AudioConverterRef c, UInt32 *packets, AudioBufferList *data, AudioStreamPacketDescription **desc, void *ref);
enum {
    noErr = 0,
    kAudioUnitType_Output = 0x61756f75 /* 'auou' */, kAudioUnitSubType_RemoteIO = 0x72696f63 /* 'rioc' */, kAudioUnitSubType_DefaultOutput = 0x64656620 /* 'def ' */,
    kAudioUnitManufacturer_Apple = 0x6170706c /* 'appl' */,
    kAudioFormatLinearPCM = 0x6c70636d /* 'lpcm' */, kAudioFormatMPEG4AAC = 0x61616320 /* 'aac ' */,
    kLinearPCMFormatFlagIsSignedInteger = 1u << 2, kLinearPCMFormatFlagIsPacked = 1u << 3,
    kAudioUnitProperty_StreamFormat = 8, kAudioUnitProperty_SetRenderCallback = 23,
    kAudioUnitScope_Global = 0, kAudioUnitScope_Input = 1, kAudioUnitScope_Output = 2,
    kAudioConverterDecompressionMagicCookie = 0x646d6763 /* 'dmgc' */,
};
AudioComponent AudioComponentFindNext(AudioComponent after, const AudioComponentDescription *desc);
OSStatus AudioComponentInstanceNew(AudioComponent c, AudioComponentInstance *out);
OSStatus AudioComponentInstanceDispose(AudioComponentInstance i);
OSStatus AudioUnitInitialize(AudioUnit u);
OSStatus AudioUnitUninitialize(AudioUnit u);
OSStatus AudioUnitSetProperty(AudioUnit u, AudioUnitPropertyID id, AudioUnitScope scope, AudioUnitElement el, const void *data, UInt32 size);
OSStatus AudioUnitGetProperty(AudioUnit u, AudioUnitPropertyID id, AudioUnitScope scope, AudioUnitElement el, void *data, UInt32 *size);
OSStatus AudioOutputUnitStart(AudioUnit u);
OSStatus AudioOutputUnitStop(AudioUnit u);
OSStatus AudioConverterNew(const AudioStreamBasicDescription *in, const AudioStreamBasicDescription *out, AudioConverterRef *c);
OSStatus AudioConverterDispose(AudioConverterRef c);
OSStatus AudioConverterSetProperty(AudioConverterRef c, AudioConverterPropertyID id, UInt32 size, const void *data);
OSStatus AudioConverterFillComplexBuffer(AudioConverterRef c, AudioConverterComplexInputDataProc proc, void *ref, UInt32 *packets, AudioBufferList *out, AudioStreamPacketDescription *desc);
