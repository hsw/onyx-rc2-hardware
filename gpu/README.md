# GPU: Mali-400 MP2, EGL and OpenGL ES on the RC2

What the RC2's GPU stack offers to an Android app: EGL, OpenGL ES 1.1 and 2.0 strings, extensions, configs, limits, shader
precision, entry points, functional checks, GPU memory, and what Chromium 83 makes of it. Measured on one RC2 (pcb V1.73) on
2026-10-15 with a small probe ([`probe/`](probe/)); raw output [`egl-probe-output.txt`](egl-probe-output.txt), tables
[`data/`](data/).

Confidence marks as in the [top README](../README.md#confidence-marks): everything here is **[CONFIRMED]** (measured on the
device) unless marked; readings of the public AOSP 4.4 and Chromium 83 sources are [STRONG].

## The stack

| Layer | What |
|---|---|
| GPU | ARM **Mali-400 MP2**: GP + two PP cores at 0x10090000 ([`../soc/README.md`](../soc/README.md) §1); `GL_RENDERER` says only "Mali-400 MP" |
| Kernel driver | `mali.ko` + `ump.ko` **r3p2-01rel0** (API version 19), external modules of the stock 3.0.36+ kernel ([`../kernel/config-reconstruction.md`](../kernel/config-reconstruction.md)) |
| Userspace driver | the stock firmware's Mali r3p2 userspace: `libEGL_mali.so`, `libGLESv1_CM_mali.so`, `libGLESv2_mali.so` (thin forwarders into `libMali.so`) |
| Android | the measurement ran on an Android 4.4.2 (KitKat) userspace built for the RC2, on the stock kernel and with the stock Mali userspace above (stock firmware: Android 4.2.2). Apps reach the driver through AOSP's `libEGL.so` ("META-EGL") |
| Device nodes | `/dev/mali` (10, 38) and `/dev/ump` (245, 0), both `crw-rw-rw-`: any app or the adb shell can use the GPU |

## The probe

[`probe/egl_probe.c`](probe/egl_probe.c) is a single C file for Android: it creates EGL contexts on 64×64 pbuffers (no
window, no gralloc buffers) and prints `## section` blocks of tab-separated lines with no pointers or timings, so two runs
diff cleanly. With `--tsv DIR` it also writes `configs.tsv`, `extensions.tsv`, `limits.tsv`, `procs.tsv`, `checks.tsv`.
Every job (Chromium's checks, EGL, the driver's EGL, GLES 1.1, GLES 2.0, then one job per functional check) runs in a forked
child with a timeout, so a driver crash or hang costs one section, not the run.

- **Two EGL layers.** The app side is AOSP's `libEGL.so`; the `egl-vendor` job also `dlopen`s the driver's
  `/system/lib/egl/libEGL_mali.so` and asks it directly (strings, extensions, `eglGetProcAddress`).
- **Entry points.** [`probe/gen_procs.py`](probe/gen_procs.py) turns the extension blocks of `EGL/eglext.h`,
  `GLES/glext.h` and `GLES2/gl2ext.h` into an extension → function table at build time;
  [`probe/extra_procs.txt`](probe/extra_procs.txt) adds names the headers lack. Each name is asked of the app's
  `eglGetProcAddress` and of the driver's, both for extensions the API advertises and for all others. A made-up name is
  asked as a control.
- **Build.** [`probe/build.sh`](probe/build.sh) with an Android NDK: `CC` = an ARM Android compiler, `SYSROOT` = the
  android-18 platform (or a newer NDK's clang wrapper and `GL_INCLUDE`); the result is a PIE armeabi-v7a executable. Run
  it over adb as the shell user: `adb push egl_probe /data/local/tmp/ && adb shell /data/local/tmp/egl_probe --tsv
  /data/local/tmp/egl-probe-tsv`. The published output was built with GCC 4.7 against the android-18 sysroot and the
  Android 4.4 EGL/GLES headers.
- **Runs.** As root and as the shell user (uid 2000) on a userdebug build: byte-identical output. All 11 jobs `ok`.

## EGL

| | app (`libEGL.so`) | driver (`libEGL_mali.so`) |
|---|---|---|
| `eglInitialize` | 1.4 | 1.4 |
| `EGL_VENDOR` | Android | ARM |
| `EGL_VERSION` | `1.4 Android META-EGL` | `1.4 Linux-r3p2-01rel0` |
| `EGL_CLIENT_APIS` | OpenGL_ES | OpenGL_ES |
| extensions | 12 | 11 |

- Both: `EGL_KHR_image`, `EGL_KHR_image_base`, `EGL_KHR_image_pixmap`, `EGL_KHR_gl_texture_2D_image`,
  `EGL_KHR_gl_texture_cubemap_image`, `EGL_KHR_gl_renderbuffer_image`, `EGL_KHR_fence_sync`, `EGL_KHR_reusable_sync`,
  `EGL_ANDROID_image_native_buffer`, `EGL_ANDROID_recordable`.
- App only: `EGL_KHR_get_all_proc_addresses`, `EGL_ANDROID_presentation_time` (AOSP's own).
- Driver only: `EGL_ANDROID_framebuffer_target` (AOSP 4.4's extension whitelist drops it; SurfaceFlinger queries the config
  attribute directly) [STRONG for the reason].
- Absent: `EGL_KHR_wait_sync`, `EGL_ANDROID_native_fence_sync`, `EGL_KHR_create_context`, `EGL_KHR_surfaceless_context`,
  `EGL_EXT_buffer_age`, `EGL_KHR_partial_update`, swap with damage.

**Configs: 21** ([`data/configs.tsv`](data/configs.tsv)), all renderable as ES 1.x and ES 2.0. **No ES 3 config:**
`eglChooseConfig` with `EGL_OPENGL_ES3_BIT_KHR` gives 0 configs and `EGL_BAD_ATTRIBUTE`.

| Colour (native visual id) | Config ids | Depth / stencil | Samples |
|---|---|---|---|
| RGB565 (4) | 5, 3, 4, 29 | 24/8 (29: none) | 0, 4, 16 (id 4) |
| RGBA5551 (6) | 19, 18, 20 | 24/8 | 0, 4, 16 (id 20) |
| RGBA4444 (7) | 21, 22, 23 | 24/8 | 0, 4, 16 (id 23) |
| RGBA8888 (1) | 9, 12, 15, 30, 40 | 24/8 (30: none) | 0, 4, 16 (id 15) |
| RGBX8888 (2) | 38, 31, 32 | 38: 24/8, 31: none, 32: 24/0 | 0 |
| BGRA8888 (5) | 33 | 24/8 | 0 |
| L8, L8A8 (0) | 13, 14 | none | 0, pixmap only |

- The 16-sample configs and 38, 13, 14 are `EGL_NON_CONFORMANT_CONFIG`; 40 (RGBA8888, window only) is `EGL_SLOW_CONFIG`.
  The RGBA5551 and RGBA4444 configs have no pixmap surface.
- `EGL_RECORDABLE_ANDROID` on 3, 4, 5, 9, 12, 15, 33, 40. **`EGL_FRAMEBUFFER_TARGET_ANDROID` on one config only: 33**
  (BGRA8888, 24/8).
- Swap interval 0..10; pbuffers up to 4096 × 4096; `EGL_SWAP_BEHAVIOR_PRESERVED_BIT` on every window config.

## OpenGL ES 1.1 and 2.0

| | GLES 1.1 | GLES 2.0 |
|---|---|---|
| `GL_VENDOR` / `GL_RENDERER` | ARM / Mali-400 MP | ARM / Mali-400 MP |
| `GL_VERSION` | `OpenGL ES-CM 1.1` | `OpenGL ES 2.0` |
| `GL_SHADING_LANGUAGE_VERSION` | — | `OpenGL ES GLSL ES 1.00` |
| extensions | 30 | 21 |

**GLES 2.0 extensions:** `GL_ARM_mali_program_binary`, `GL_ARM_mali_shader_binary`, `GL_ARM_rgba8`,
`GL_EXT_blend_minmax`, `GL_EXT_debug_marker`, `GL_EXT_discard_framebuffer`, `GL_EXT_multisampled_render_to_texture`,
`GL_EXT_robustness`, `GL_EXT_shader_texture_lod`, `GL_EXT_texture_format_BGRA8888`, `GL_OES_EGL_image`,
`GL_OES_EGL_image_external`, `GL_OES_EGL_sync`, `GL_OES_compressed_ETC1_RGB8_texture`, `GL_OES_depth24`,
`GL_OES_depth_texture`, `GL_OES_get_program_binary`, `GL_OES_packed_depth_stencil`, `GL_OES_rgb8_rgba8`,
`GL_OES_standard_derivatives`, `GL_OES_texture_npot`.
- `GL_EXT_debug_marker` is added to the string by AOSP's `libEGL` when the driver lacks it [STRONG]; the driver returns
  no entry points for it.
- **Absent:** `GL_OES_element_index_uint` (16-bit indices only), `GL_OES_vertex_array_object`, `GL_OES_mapbuffer`,
  `GL_OES_texture_float` / `half_float`, `GL_EXT_texture_rg`, `GL_OES_texture_3D`, `GL_EXT_texture_filter_anisotropic`,
  `GL_EXT_draw_buffers`, instancing, occlusion and timer queries, `GL_KHR_debug`, `GL_OES_fragment_precision_high`.

**GLES 1.1 extensions:** the 2.0 list without the two ARM binary formats, `GL_OES_get_program_binary`,
`GL_EXT_blend_minmax`, `GL_EXT_shader_texture_lod` and `GL_OES_standard_derivatives`, plus `GL_OES_byte_coordinates`,
`compressed_paletted_texture`, `draw_texture`, `extended_matrix_palette`, `fixed_point`, `framebuffer_object`,
`matrix_get`, `matrix_palette`, `point_size_array`, `point_sprite`, `query_matrix`, `read_format`, `single_precision`,
`stencil8`, `texture_cube_map` (all `GL_OES_`).

**GLES 2.0 limits** (all of them in [`data/limits.tsv`](data/limits.tsv)):

| Limit | Value |
|---|---|
| `GL_MAX_TEXTURE_SIZE` / `GL_MAX_RENDERBUFFER_SIZE` | 4096 / 4096 (but see the checks) |
| `GL_MAX_CUBE_MAP_TEXTURE_SIZE` | 1024 |
| `GL_MAX_VIEWPORT_DIMS` | 4096 × 4096 |
| `GL_MAX_TEXTURE_IMAGE_UNITS` / `GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS` | 8 / 8 |
| `GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS` | **0**: no texture fetch in vertex shaders |
| `GL_MAX_VERTEX_ATTRIBS` | 16 |
| `GL_MAX_VERTEX_UNIFORM_VECTORS` / `GL_MAX_FRAGMENT_UNIFORM_VECTORS` | 256 / 256 |
| `GL_MAX_VARYING_VECTORS` | 12 |
| `GL_MAX_SAMPLES_EXT` | 4 |
| point size / line width | 1..100 / 1..100 |
| `GL_SUBPIXEL_BITS` | 4 |
| compressed texture formats | ETC1 only |
| shader / program binary formats | `GL_MALI_SHADER_BINARY_ARM` 0x8f60 / `GL_MALI_PROGRAM_BINARY_ARM` 0x8f61 |
| implementation read format (RGBA8888 pbuffer) | `GL_RGB` / `GL_UNSIGNED_SHORT_5_6_5` |

**GLES 1.1 limits:** 8 lights, 1 user clip plane, 8 texture units, texture 4096, cube map 1024, renderbuffer 4096, matrix
stacks 32 deep, 32 palette matrices, 4 vertex units, smooth line width 0.25..100, 11 compressed formats (10 paletted + ETC1).

**Shader precision** (`glGetShaderPrecisionFormat`: range min/max, precision bits):

| Shader | low float | medium float | high float | low / medium int | high int |
|---|---|---|---|---|---|
| vertex | 127/127, 23 | 127/127, 23 | 127/127, 23 | 24/24 | 24/24 |
| fragment | 15/15, 10 | 15/15, 10 | **0/0, 0** | 11/11 | **0** |

Vertex shaders run at fp32. Fragment shaders run at fp16 (lowp = mediump) and have **no highp**.

## Entry points

Counts from [`data/procs.tsv`](data/procs.tsv). "App" is `eglGetProcAddress` of AOSP's `libEGL.so`, "driver" that of
`libEGL_mali.so`. The made-up control name returns NULL from both.

| API | advertised extensions: rows, app non-NULL, driver non-NULL | other extensions: rows, app non-NULL, driver non-NULL |
|---|---|---|
| EGL | app 14 rows, driver 13 rows: all non-NULL | app 52 rows: 11; driver 53 rows: **0** |
| GLES 1.1 | 91: app 91, driver 44 | 49: app 49, driver **0** |
| GLES 2.0 | 14: app 14, driver 11 | 131: app 111, driver **0** |

- **The driver has no hidden entry points:** no function of an extension it does not advertise comes back from it.
- **A non-NULL pointer from the app side is no proof of support.** AOSP 4.4's `eglGetProcAddress` returns the wrapper
  that `libGLESv2`/`libGLESv1_CM` export for any name they know; at load time each wrapper was bound to the driver's
  function or to a stub that only logs "called unimplemented OpenGL ES API" [STRONG, AOSP 4.4 `eglApi.cpp`, `Loader.cpp`].
  So `glBindVertexArrayOES`, `glMapBufferOES`, `glTexStorage2DEXT`, `glGenQueriesEXT` and the NV/QCOM/AMD functions are
  non-NULL for an app and do nothing. Check the extension string, not the pointer.
- EGL: the 11 non-NULL pointers of non-advertised extensions are `libEGL` wrappers (`eglLockSurfaceKHR`,
  `eglWaitSyncKHR`, `eglGetSystemTimeNV`, `eglGetRenderBufferANDROID`, …) over a driver that implements none of them.
  `eglSetBlobCacheFuncsANDROID`, `eglDupNativeFenceFDANDROID` and the IMG hibernate pair are filtered to NULL.
- Advertised, but NULL from the driver's `eglGetProcAddress`: the 39 `GL_OES_fixed_point` `…xOES` and 6
  `GL_OES_single_precision` `…fOES` names (ES 1.1 core has the unsuffixed functions), `glGetnUniformfvEXT` /
  `glGetnUniformivEXT` of `GL_EXT_robustness`, the three `GL_EXT_debug_marker` functions. Whether the driver libraries export
  any of them as symbols (AOSP's loader also tries `dlsym`) is [VERIFY].

## Functional checks

An ES 2.0 context on a pbuffer; each check sets up, draws or clears, reads back and compares
([`data/checks.tsv`](data/checks.tsv)).

| Check | Result | Detail |
|---|---|---|
| FBO colour: RGBA8 texture; RGBA8, RGB8, RGB565, RGBA4, RGB5_A1 renderbuffers | PASS ×6 | complete; clear and read back exact |
| FBO RGBA8 texture + depth16 / depth24 / stencil8 / depth16 + stencil8 / packed depth24-stencil8 / 16-bit depth texture | PASS ×6 | complete; read back exact |
| POT 64×64 with mipmaps (control) | PASS | sampled |
| NPOT 100×60: clamp, repeat, clamp + `glGenerateMipmap` | PASS ×3 | full NPOT support |
| `fragment-highp-compiles` | PASS | a fragment shader with `precision highp float` compiles, although HIGH_FLOAT reports range 0 |
| **`fragment-highp-macro`** | **FAIL** | `GL_FRAGMENT_PRECISION_HIGH` is not defined: no highp in fragment shaders |
| `samplerExternalOES` shader | PASS | compiles and links |
| `glReadPixels` RGBA / UNSIGNED_BYTE | PASS | value read as written |
| `glReadPixels` implementation format | PASS | RGB / 565 |
| **`max-texture-rgba8-alloc`** | **FAIL** | 4096 × 4096 RGBA8 (64 MiB): `glTexImage2D` no error, framebuffer complete, clear and read no error, but the far corner reads **00000000**: the allocation fails silently |

- Fragment highp: shaders written for `GL_FRAGMENT_PRECISION_HIGH` take their mediump path; a shader that declares `highp`
  still compiles, probably at fp16 (the Mali-400 fragment processor has no fp32) [STRONG].
- Max texture: the advertised 4096² is not usable in RGBA8, and there is no `GL_OUT_OF_MEMORY` to tell. The largest size
  that works was not searched [VERIFY]. Check the content, not `glGetError`.

## GPU memory

GL allocations live in `/dev/mali` and `/dev/ump` mappings and hardly show in an app's PSS (≤ 0.3 MB "Other dev"). The
drivers count them in debugfs (root): `/sys/kernel/debug/mali/memory_usage`, `/sys/kernel/debug/ump/memory_usage`. Same
day, 512 MiB RAM:

| State | Mali | UMP |
|---|---|---|
| nothing open (launcher, system UI) | 27.5 MB | 33.5 MB |
| Bromite 83 on a long Wikipedia page | 46 MB | 45 MB |
| AOSP Browser (HWUI) on the same page | 33.5 MB | 39.5 MB |

Chromium's GL costs ~31 MB over the idle system; the counters stay flat while scrolling.

## What Chromium 83 makes of it

Bromite 83.0.4103.119 (a Chromium 83 build), `chrome://gpu` on the RC2:
- **GPU in the browser process** (`--in-process-gpu`: Chromium's low-end mode on a 512 MB device), validating command
  decoder, no sandbox. Compositing, rasterization, canvas and WebGL hardware accelerated; GPU process crash count 0.
  WebGL2 is listed as "Hardware accelerated" too, although no ES 3 context exists (not tested).
- Mali-400 is not on Chromium 83's software rendering list (`software_rendering_list.json` entry 96 even exempts
  `Mali-4.*` on Android ≥ 4.4 from its GPU raster/canvas block). `gpu_driver_bug_list.json` applies the Mali-4xx
  workarounds shown on the page: `use_virtualized_gl_contexts` (flush ordering, entry 31), `exit_on_context_lost`
  (entry 119), `disable_discard_framebuffer` (corruption, entry 105), `use_non_zero_size_for_client_side_stream_buffers`
  (entry 24), `max_copy_texture_chromium_size_262144` (pre-Lollipop, entry 120), `use_client_side_arrays_for_stream_buffers`,
  plus the Android-wide ones (texture size 4096, MSAA 4, one raster thread) [STRONG for the entry numbers].
- **`EGL_KHR_fence_sync` is disabled**: "Testing fences was broken on Mali ES2 drivers" (entry 77, crbug 378691, 373360,
  371530, 398964; Mali ES2 drivers on Android up to 4.4.4), listed under "Disabled Extensions".
- Consequence for an Android WebView built from Chromium 83: its GL draw-functor path needs
  `can_support_threaded_texture_mailbox`, that is `EGL_KHR_fence_sync`, `EGL_KHR_image_base`, `EGL_KHR_gl_texture_2D_image`
  and `GL_OES_EGL_image`. The driver has all four and they work (the probe's `chromium-q3` section: fence create and wait,
  an EGLImage from a texture, `glEGLImageTargetTexture2DOES`, a second shared context), but with entry 77 applied Chromium
  sees no fence and reports no mailbox support, so that path stays off unless the workaround is overridden.

## Files

| Path | What |
|---|---|
| [`egl-probe-output.txt`](egl-probe-output.txt) | the probe's text output (root run; the shell-user run is identical) |
| [`data/`](data/) | `configs.tsv`, `extensions.tsv`, `limits.tsv`, `procs.tsv` (api, layer, extension, function, advertised, result, note), `checks.tsv` |
| [`probe/`](probe/) | `egl_probe.c`, `gen_procs.py`, `extra_procs.txt`, `build.sh` (MIT) |
