#pragma once
#include "engine/xbg_game.h"
#ifdef __cplusplus
extern "C" {
#endif
/* shader_output_viewport_index / multiview: what the front end enabled at vkCreateDevice for the multi-viewport draw
 * (xbg_game_set_viewport_features; VkPhysicalDeviceVulkan12Features.shaderOutputViewportIndex + shaderOutputLayer or
 * VK_EXT_shader_viewport_index_layer, and VkPhysicalDeviceMultiviewFeatures.multiview), as sampler_mirror_clamp_to_edge is. */
typedef struct dm_vk_config {uint32_t size;xbg_game_config game;VkBool32 sampler_mirror_clamp_to_edge;int display_hz;int (*has_window)(void *userdata);VkBool32 shader_output_viewport_index,multiview,depth_clip_control;} dm_vk_config;
/* Call before dm_main. Device/queue/window owned by frontend; Vulkan use serialized.
 * shader_directory must contain genuine .xgs exported from matching control blobs. */
int dm_vk_initialize(const dm_vk_config *config,char *error,size_t bytes);
#ifdef __cplusplus
}
#endif
