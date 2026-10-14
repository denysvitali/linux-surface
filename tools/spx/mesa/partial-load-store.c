/*
 * Headless Turnip A680 partial-render-area LOAD/STORE regression test.
 * Only libc and libvulkan; Vulkan 1.2, no optional features or extensions.
 * Build: gcc -std=c11 -O2 -Wall -Wextra -Wpedantic partial-load-store.c -lvulkan -o partial-load-store
 * On this machine without system Vulkan headers, add:
 *   -I/var/tmp/spx-mesa-26.2.1/include
 * Run separately with TU_DEBUG=gmem and TU_DEBUG=sysmem (do not combine).
 * The program never changes TU_DEBUG. Default/autotune success alone does
 * not establish that GMEM was used. No GPU run was made during development.
 * Diagnostics: --passes N [--stop-first], or --single X Y W H.
 * Single-only: --no-clear, --color RRGGBBAA, --full-rect,
 * --load-clear RRGGBBAA, --draw, --dump-area. See --help.
 * --help lists bounds; detailed reports describe the first bad pass.
 * Exit: 0 all pixels match; 1 mismatch; 2 setup/Vulkan error; 77 unsupported.
 *
 * Every partial pass LOADs and STOREs one RGBA8_UNORM attachment. Some
 * clears are inset, preserving sentinel pixels *inside* the render area;
 * every checkpoint compares all pixels, including those outside all damage.
 * Original modes use endpoint clear values (0/1). Single probes convert
 * explicit RGBA bytes to float by dividing by 255. The initial
 * pattern is uploaded as bytes, so it may use all 256 channel values.
 * See ANALYSIS.md for source-path justification and two static VU reviews.
 */
#include <vulkan/vulkan.h>
#include <inttypes.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define FORMAT VK_FORMAT_R8G8B8A8_UNORM
#define FRAMES 3u
#define PASSES 32u
#define MIB (UINT64_C(1024) * 1024)
#define COLOR_ACCESS (VK_ACCESS_COLOR_ATTACHMENT_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT)
#define CHECK(call) do { VkResult r_ = (call); if (r_ != VK_SUCCESS) { \
    fprintf(stderr, "%s:%d: %s -> VkResult %d\n", __FILE__, __LINE__, #call, r_); \
    exit(2); } } while (0)

static VkInstance instance;
static VkPhysicalDevice physical;
static VkDevice device;
static VkQueue queue;
static uint32_t family;
static VkCommandPool pool;
static VkCommandBuffer cmd;
static VkFence fence;
static VkRenderPass render_pass;
static VkPipelineLayout pipeline_layout;
static VkPipeline pipeline;
static struct {
    int no_clear, color_set, full_rect, load_clear, draw, dump_area;
    uint8_t color[4], load_color[4];
} options = { .color = {255, 0, 0, 0} };
static VkExtent2D granularity;
static VkPhysicalDeviceMemoryProperties memory_props;
static VkPhysicalDeviceProperties props;

struct target {
    uint32_t w, h;
    size_t bytes;
    VkImage image;
    VkDeviceMemory image_memory;
    VkImageView view;
    VkFramebuffer framebuffer;
    VkBuffer staging;
    VkDeviceMemory staging_memory;
    uint8_t *mapped, *expected;
};

static void stop(const char *why, int status)
{
    fprintf(stderr, "%s: %s\n", status == 77 ? "SKIP" : "ERROR", why);
    exit(status);
}

static void *allocate(size_t n)
{
    void *p = malloc(n ? n : 1);
    if (!p) stop("CPU allocation failed", 2);
    return p;
}

static uint32_t memory_type(uint32_t bits, VkMemoryPropertyFlags required,
                            VkMemoryPropertyFlags preferred)
{
    uint32_t best = UINT32_MAX, best_score = 0;
    for (uint32_t i = 0; i < memory_props.memoryTypeCount; ++i) {
        VkMemoryPropertyFlags f = memory_props.memoryTypes[i].propertyFlags;
        if (!(bits & (1u << i)) || (f & required) != required ||
            (f & (VK_MEMORY_PROPERTY_LAZILY_ALLOCATED_BIT | VK_MEMORY_PROPERTY_PROTECTED_BIT)))
            continue;
        uint32_t score = 1;
        for (uint32_t b = 0; b < 32; ++b)
            if ((f & preferred) & (1u << b)) ++score;
        if (score > best_score) { best = i; best_score = score; }
    }
    if (best == UINT32_MAX) stop("No suitable memory type", 77);
    return best;
}

static void init_vulkan(void)
{
    VkApplicationInfo app = {
        .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName = "a680-partial-load-store", .apiVersion = VK_API_VERSION_1_2
    };
    VkInstanceCreateInfo ici = {
        .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app
    };
    CHECK(vkCreateInstance(&ici, NULL, &instance));
    uint32_t count = 0;
    CHECK(vkEnumeratePhysicalDevices(instance, &count, NULL));
    if (!count || count > 64) stop("No devices, or unexpected device count", 77);
    VkPhysicalDevice *devices = allocate(count * sizeof(*devices));
    CHECK(vkEnumeratePhysicalDevices(instance, &count, devices));
    for (uint32_t i = 0; i < count && !physical; ++i) {
        VkPhysicalDeviceProperties p;
        vkGetPhysicalDeviceProperties(devices[i], &p);
        if (p.apiVersion < VK_API_VERSION_1_2 || p.vendorID != 0x5143 ||
            (p.deviceType != VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU &&
             p.deviceType != VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU)) continue;
        VkPhysicalDeviceDriverProperties driver = {
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES
        };
        VkPhysicalDeviceProperties2 p2 = {
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext = &driver
        };
        vkGetPhysicalDeviceProperties2(devices[i], &p2);
        if (driver.driverID != VK_DRIVER_ID_MESA_TURNIP || !strstr(p.deviceName, "680"))
            continue;
        uint32_t nq = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(devices[i], &nq, NULL);
        VkQueueFamilyProperties *qp = allocate(nq * sizeof(*qp));
        vkGetPhysicalDeviceQueueFamilyProperties(devices[i], &nq, qp);
        for (uint32_t q = 0; q < nq; ++q) {
            /* A graphics queue supports transfer commands even when the
             * redundant TRANSFER bit is not reported. No ownership transfer. */
            if (qp[q].queueCount && (qp[q].queueFlags & VK_QUEUE_GRAPHICS_BIT)) {
                physical = devices[i]; family = q; props = p;
                printf("Device: %s; driver: %s (%s); queue family %u\n",
                       p.deviceName, driver.driverName, driver.driverInfo, family);
                break;
            }
        }
        free(qp);
    }
    free(devices);
    if (!physical) stop("No hardware Mesa Turnip A680 with Vulkan 1.2 graphics queue", 77);
    vkGetPhysicalDeviceMemoryProperties(physical, &memory_props);
    VkFormatProperties fp;
    vkGetPhysicalDeviceFormatProperties(physical, FORMAT, &fp);
    VkFormatFeatureFlags needed = VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT |
        VK_FORMAT_FEATURE_TRANSFER_SRC_BIT | VK_FORMAT_FEATURE_TRANSFER_DST_BIT;
    if ((fp.optimalTilingFeatures & needed) != needed)
        stop("RGBA8_UNORM lacks required optimal-tiling features", 77);
    float priority = 1.0f;
    VkDeviceQueueCreateInfo qci = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority
    };
    VkDeviceCreateInfo dci = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
        .queueCreateInfoCount = 1, .pQueueCreateInfos = &qci
    };
    CHECK(vkCreateDevice(physical, &dci, NULL, &device));
    vkGetDeviceQueue(device, family, 0, &queue);
    VkCommandPoolCreateInfo pci = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
        .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, .queueFamilyIndex = family
    };
    CHECK(vkCreateCommandPool(device, &pci, NULL, &pool));
    VkCommandBufferAllocateInfo cai = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = pool,
        .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1
    };
    CHECK(vkAllocateCommandBuffers(device, &cai, &cmd));
    VkFenceCreateInfo fci = { .sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO };
    CHECK(vkCreateFence(device, &fci, NULL, &fence));
    VkAttachmentDescription attachment = {
        .format = FORMAT, .samples = VK_SAMPLE_COUNT_1_BIT,
        .loadOp = options.load_clear ? VK_ATTACHMENT_LOAD_OP_CLEAR : VK_ATTACHMENT_LOAD_OP_LOAD,
        .storeOp = VK_ATTACHMENT_STORE_OP_STORE,
        .stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE,
        .stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE,
        .initialLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
        .finalLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL
    };
    VkAttachmentReference color = { 0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL };
    VkSubpassDescription subpass = {
        .pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS,
        .colorAttachmentCount = 1, .pColorAttachments = &color
    };
    /* Full-image barriers outside every pass provide all external
     * dependencies. There are no automatic layout transitions in this RP. */
    VkRenderPassCreateInfo rpci = {
        .sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO,
        .attachmentCount = 1, .pAttachments = &attachment,
        .subpassCount = 1, .pSubpasses = &subpass
    };
    CHECK(vkCreateRenderPass(device, &rpci, NULL, &render_pass));
    vkGetRenderAreaGranularity(device, render_pass, &granularity);
    printf("Reported render-area granularity: %ux%u (performance hint)\n",
           granularity.width, granularity.height);
}

/* Generated with glslangValidator -V --target-env vulkan1.2 -Os;
 * validated with spirv-val --target-env vulkan1.2. No runtime compiler.
 * Vertex GLSL: out gl_PerVertex { vec4 gl_Position; };
 * int v = gl_VertexIndex % 3;
 * vec2 p = vec2(float((v << 1) & 2), float(v & 2));
 * gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
 * Fragment GLSL: layout(push_constant) uniform Color { vec4 rgba; } pc;
 * layout(location=0) out vec4 out_color; out_color = pc.rgba;
 * Both use #version 450, void main(), and only Shader capability.
 */
static const uint32_t vert_spirv[] = {
    0x07230203u, 0x00010500u, 0x0008000bu, 0x0000002eu, 0x00000000u, 0x00020011u, 0x00000001u, 0x0006000bu,
    0x00000001u, 0x4c534c47u, 0x6474732eu, 0x3035342eu, 0x00000000u, 0x0003000eu, 0x00000000u, 0x00000001u,
    0x0007000fu, 0x00000000u, 0x00000004u, 0x6e69616du, 0x00000000u, 0x0000000au, 0x0000001fu, 0x00030003u,
    0x00000002u, 0x000001c2u, 0x00040005u, 0x00000004u, 0x6e69616du, 0x00000000u, 0x00060005u, 0x0000000au,
    0x565f6c67u, 0x65747265u, 0x646e4978u, 0x00007865u, 0x00060005u, 0x0000001du, 0x505f6c67u, 0x65567265u,
    0x78657472u, 0x00000000u, 0x00060006u, 0x0000001du, 0x00000000u, 0x505f6c67u, 0x7469736fu, 0x006e6f69u,
    0x00030005u, 0x0000001fu, 0x00000000u, 0x00040047u, 0x0000000au, 0x0000000bu, 0x0000002au, 0x00030047u,
    0x0000001du, 0x00000002u, 0x00050048u, 0x0000001du, 0x00000000u, 0x0000000bu, 0x00000000u, 0x00020013u,
    0x00000002u, 0x00030021u, 0x00000003u, 0x00000002u, 0x00040015u, 0x00000006u, 0x00000020u, 0x00000001u,
    0x00040020u, 0x00000009u, 0x00000001u, 0x00000006u, 0x0004003bu, 0x00000009u, 0x0000000au, 0x00000001u,
    0x0004002bu, 0x00000006u, 0x0000000cu, 0x00000003u, 0x00030016u, 0x0000000eu, 0x00000020u, 0x00040017u,
    0x0000000fu, 0x0000000eu, 0x00000002u, 0x0004002bu, 0x00000006u, 0x00000013u, 0x00000001u, 0x0004002bu,
    0x00000006u, 0x00000015u, 0x00000002u, 0x00040017u, 0x0000001cu, 0x0000000eu, 0x00000004u, 0x0003001eu,
    0x0000001du, 0x0000001cu, 0x00040020u, 0x0000001eu, 0x00000003u, 0x0000001du, 0x0004003bu, 0x0000001eu,
    0x0000001fu, 0x00000003u, 0x0004002bu, 0x00000006u, 0x00000020u, 0x00000000u, 0x0004002bu, 0x0000000eu,
    0x00000022u, 0x40000000u, 0x0004002bu, 0x0000000eu, 0x00000024u, 0x3f800000u, 0x0004002bu, 0x0000000eu,
    0x00000027u, 0x00000000u, 0x00040020u, 0x0000002bu, 0x00000003u, 0x0000001cu, 0x0005002cu, 0x0000000fu,
    0x0000002du, 0x00000024u, 0x00000024u, 0x00050036u, 0x00000002u, 0x00000004u, 0x00000000u, 0x00000003u,
    0x000200f8u, 0x00000005u, 0x0004003du, 0x00000006u, 0x0000000bu, 0x0000000au, 0x0005008bu, 0x00000006u,
    0x0000000du, 0x0000000bu, 0x0000000cu, 0x000500c4u, 0x00000006u, 0x00000014u, 0x0000000du, 0x00000013u,
    0x000500c7u, 0x00000006u, 0x00000016u, 0x00000014u, 0x00000015u, 0x0004006fu, 0x0000000eu, 0x00000017u,
    0x00000016u, 0x000500c7u, 0x00000006u, 0x00000019u, 0x0000000du, 0x00000015u, 0x0004006fu, 0x0000000eu,
    0x0000001au, 0x00000019u, 0x00050050u, 0x0000000fu, 0x0000001bu, 0x00000017u, 0x0000001au, 0x0005008eu,
    0x0000000fu, 0x00000023u, 0x0000001bu, 0x00000022u, 0x00050083u, 0x0000000fu, 0x00000026u, 0x00000023u,
    0x0000002du, 0x00050051u, 0x0000000eu, 0x00000028u, 0x00000026u, 0x00000000u, 0x00050051u, 0x0000000eu,
    0x00000029u, 0x00000026u, 0x00000001u, 0x00070050u, 0x0000001cu, 0x0000002au, 0x00000028u, 0x00000029u,
    0x00000027u, 0x00000024u, 0x00050041u, 0x0000002bu, 0x0000002cu, 0x0000001fu, 0x00000020u, 0x0003003eu,
    0x0000002cu, 0x0000002au, 0x000100fdu, 0x00010038u,
};

static const uint32_t frag_spirv[] = {
    0x07230203u, 0x00010500u, 0x0008000bu, 0x00000012u, 0x00000000u, 0x00020011u, 0x00000001u, 0x0006000bu,
    0x00000001u, 0x4c534c47u, 0x6474732eu, 0x3035342eu, 0x00000000u, 0x0003000eu, 0x00000000u, 0x00000001u,
    0x0007000fu, 0x00000004u, 0x00000004u, 0x6e69616du, 0x00000000u, 0x00000009u, 0x0000000cu, 0x00030010u,
    0x00000004u, 0x00000007u, 0x00030003u, 0x00000002u, 0x000001c2u, 0x00040005u, 0x00000004u, 0x6e69616du,
    0x00000000u, 0x00050005u, 0x00000009u, 0x5f74756fu, 0x6f6c6f63u, 0x00000072u, 0x00040005u, 0x0000000au,
    0x6f6c6f43u, 0x00000072u, 0x00050006u, 0x0000000au, 0x00000000u, 0x61626772u, 0x00000000u, 0x00030005u,
    0x0000000cu, 0x00006370u, 0x00040047u, 0x00000009u, 0x0000001eu, 0x00000000u, 0x00030047u, 0x0000000au,
    0x00000002u, 0x00050048u, 0x0000000au, 0x00000000u, 0x00000023u, 0x00000000u, 0x00020013u, 0x00000002u,
    0x00030021u, 0x00000003u, 0x00000002u, 0x00030016u, 0x00000006u, 0x00000020u, 0x00040017u, 0x00000007u,
    0x00000006u, 0x00000004u, 0x00040020u, 0x00000008u, 0x00000003u, 0x00000007u, 0x0004003bu, 0x00000008u,
    0x00000009u, 0x00000003u, 0x0003001eu, 0x0000000au, 0x00000007u, 0x00040020u, 0x0000000bu, 0x00000009u,
    0x0000000au, 0x0004003bu, 0x0000000bu, 0x0000000cu, 0x00000009u, 0x00040015u, 0x0000000du, 0x00000020u,
    0x00000001u, 0x0004002bu, 0x0000000du, 0x0000000eu, 0x00000000u, 0x00040020u, 0x0000000fu, 0x00000009u,
    0x00000007u, 0x00050036u, 0x00000002u, 0x00000004u, 0x00000000u, 0x00000003u, 0x000200f8u, 0x00000005u,
    0x00050041u, 0x0000000fu, 0x00000010u, 0x0000000cu, 0x0000000eu, 0x0004003du, 0x00000007u, 0x00000011u,
    0x00000010u, 0x0003003eu, 0x00000009u, 0x00000011u, 0x000100fdu, 0x00010038u,
};

static void create_draw_pipeline(void)
{
    /* Static Vulkan 1.2 usage review:
     * Shader-only SPIR-V 1.5; Position/VertexIndex and fragment Location 0,
     * OriginUpperLeft, Block/Offset 0 push vec4, no optional capabilities.
     * One compatible color subpass, no depth, samples=1, no vertex buffers,
     * fill/cull-none/lineWidth=1, blending and logic ops off, RGBA writes on.
     * Dynamic viewport/scissor are both set before every draw. Push range
     * offset=0,size=16 is 4-byte aligned and below core minimum limit 128;
     * fragment stage matches shader and vkCmdPushConstants. No descriptors.
     * Positive viewport dimensions/bounds are checked before recording;
     * scissor and clear rectangles fit framebuffer/renderArea, layer=0+1.
     * loadOp CLEAR supplies clearValueCount=1 for attachment 0; LOAD has a
     * defined initial layout. All operations retain STORE, external full
     * color read/write dependencies and fence-completed object lifetimes.
     */
    VkPushConstantRange range = { VK_SHADER_STAGE_FRAGMENT_BIT, 0, 4 * sizeof(float) };
    VkPipelineLayoutCreateInfo lci = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
        .pushConstantRangeCount = 1, .pPushConstantRanges = &range
    };
    CHECK(vkCreatePipelineLayout(device, &lci, NULL, &pipeline_layout));
    VkShaderModule modules[2];
    VkShaderModuleCreateInfo sci = {
        .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
        .codeSize = sizeof(vert_spirv), .pCode = vert_spirv
    };
    CHECK(vkCreateShaderModule(device, &sci, NULL, &modules[0]));
    sci.codeSize = sizeof(frag_spirv); sci.pCode = frag_spirv;
    CHECK(vkCreateShaderModule(device, &sci, NULL, &modules[1]));
    VkPipelineShaderStageCreateInfo stages[2] = {
        { .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
          .stage = VK_SHADER_STAGE_VERTEX_BIT, .module = modules[0], .pName = "main" },
        { .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
          .stage = VK_SHADER_STAGE_FRAGMENT_BIT, .module = modules[1], .pName = "main" }
    };
    VkPipelineVertexInputStateCreateInfo vi = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO
    };
    VkPipelineInputAssemblyStateCreateInfo ia = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,
        .topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST
    };
    VkPipelineViewportStateCreateInfo vp = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO,
        .viewportCount = 1, .scissorCount = 1
    };
    VkPipelineRasterizationStateCreateInfo rs = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,
        .polygonMode = VK_POLYGON_MODE_FILL, .cullMode = VK_CULL_MODE_NONE,
        .frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE, .lineWidth = 1.0f
    };
    VkPipelineMultisampleStateCreateInfo ms = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,
        .rasterizationSamples = VK_SAMPLE_COUNT_1_BIT
    };
    VkPipelineColorBlendAttachmentState blend = {
        .colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT |
                          VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT
    };
    VkPipelineColorBlendStateCreateInfo cb = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,
        .attachmentCount = 1, .pAttachments = &blend
    };
    VkDynamicState states[] = { VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR };
    VkPipelineDynamicStateCreateInfo ds = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO,
        .dynamicStateCount = 2, .pDynamicStates = states
    };
    VkGraphicsPipelineCreateInfo ci = {
        .sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO,
        .stageCount = 2, .pStages = stages, .pVertexInputState = &vi,
        .pInputAssemblyState = &ia, .pViewportState = &vp,
        .pRasterizationState = &rs, .pMultisampleState = &ms,
        .pColorBlendState = &cb, .pDynamicState = &ds,
        .layout = pipeline_layout, .renderPass = render_pass, .subpass = 0,
        .basePipelineIndex = -1
    };
    CHECK(vkCreateGraphicsPipelines(device, VK_NULL_HANDLE, 1, &ci, NULL, &pipeline));
    vkDestroyShaderModule(device, modules[0], NULL);
    vkDestroyShaderModule(device, modules[1], NULL);
}

static struct target create_target(uint32_t w, uint32_t h)
{
    struct target t = { .w = w, .h = h, .bytes = (size_t)w * h * 4 };
    if (w > props.limits.maxFramebufferWidth || h > props.limits.maxFramebufferHeight ||
        w > props.limits.maxImageDimension2D || h > props.limits.maxImageDimension2D)
        stop("Image exceeds framebuffer/image limits", 77);
    VkImageUsageFlags usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT |
        VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    VkImageFormatProperties ifp;
    VkResult result = vkGetPhysicalDeviceImageFormatProperties(physical, FORMAT,
        VK_IMAGE_TYPE_2D, VK_IMAGE_TILING_OPTIMAL, usage, 0, &ifp);
    if (result == VK_ERROR_FORMAT_NOT_SUPPORTED) stop("Image configuration unsupported", 77);
    CHECK(result);
    if (w > ifp.maxExtent.width || h > ifp.maxExtent.height ||
        ifp.maxExtent.depth < 1 || ifp.maxMipLevels < 1 || ifp.maxArrayLayers < 1 ||
        !(ifp.sampleCounts & VK_SAMPLE_COUNT_1_BIT))
        stop("Image format limits unsupported", 77);
    VkImageCreateInfo image_ci = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType = VK_IMAGE_TYPE_2D, .format = FORMAT, .extent = { w, h, 1 },
        .mipLevels = 1, .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = usage,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE, .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED
    };
    CHECK(vkCreateImage(device, &image_ci, NULL, &t.image));
    VkBufferCreateInfo buffer_ci = {
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = t.bytes,
        .usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE
    };
    CHECK(vkCreateBuffer(device, &buffer_ci, NULL, &t.staging));
    VkMemoryRequirements imr, bmr;
    vkGetImageMemoryRequirements(device, t.image, &imr);
    vkGetBufferMemoryRequirements(device, t.staging, &bmr);
    if (imr.size > ifp.maxResourceSize || imr.size > 32 * MIB || bmr.size > 32 * MIB ||
        imr.size + bmr.size + t.bytes > 96 * MIB)
        stop("Test data exceeds memory budget (driver allocations excluded)", 77);
    /* Each resource has its own allocation; explicitly dedicate it so that
     * a driver requiring dedicated memory is also handled correctly. */
    VkMemoryDedicatedAllocateInfo dedicated = {
        .sType = VK_STRUCTURE_TYPE_MEMORY_DEDICATED_ALLOCATE_INFO, .image = t.image
    };
    VkMemoryAllocateInfo mai = {
        .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .pNext = &dedicated,
        .allocationSize = imr.size,
        .memoryTypeIndex = memory_type(imr.memoryTypeBits, 0, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)
    };
    CHECK(vkAllocateMemory(device, &mai, NULL, &t.image_memory));
    CHECK(vkBindImageMemory(device, t.image, t.image_memory, 0));
    dedicated.image = VK_NULL_HANDLE;
    dedicated.buffer = t.staging;
    mai.allocationSize = bmr.size;
    mai.memoryTypeIndex = memory_type(bmr.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT,
        VK_MEMORY_PROPERTY_HOST_COHERENT_BIT | VK_MEMORY_PROPERTY_HOST_CACHED_BIT);
    CHECK(vkAllocateMemory(device, &mai, NULL, &t.staging_memory));
    CHECK(vkBindBufferMemory(device, t.staging, t.staging_memory, 0));
    void *mapping = NULL;
    CHECK(vkMapMemory(device, t.staging_memory, 0, VK_WHOLE_SIZE, 0, &mapping));
    t.mapped = mapping;
    t.expected = allocate(t.bytes);
    VkImageViewCreateInfo vci = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = t.image,
        .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = FORMAT,
        .components = { VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY,
                        VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY },
        .subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 }
    };
    CHECK(vkCreateImageView(device, &vci, NULL, &t.view));
    VkFramebufferCreateInfo fbci = {
        .sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO, .renderPass = render_pass,
        .attachmentCount = 1, .pAttachments = &t.view, .width = w, .height = h, .layers = 1
    };
    CHECK(vkCreateFramebuffer(device, &fbci, NULL, &t.framebuffer));
    printf("Image %ux%u: CPU+explicit Vulkan data allocations %.1f MiB\n", w, h,
           (double)(imr.size + bmr.size + t.bytes) / (double)MIB);
    return t;
}

static void begin_commands(void)
{
    /* All previous submissions have completed before resetting this buffer. */
    CHECK(vkResetCommandBuffer(cmd, 0));
    VkCommandBufferBeginInfo bi = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
        .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT
    };
    CHECK(vkBeginCommandBuffer(cmd, &bi));
}

static void submit_wait(void)
{
    CHECK(vkEndCommandBuffer(cmd));
    CHECK(vkResetFences(device, 1, &fence));
    VkSubmitInfo si = {
        .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1,
        .pCommandBuffers = &cmd
    };
    CHECK(vkQueueSubmit(queue, 1, &si, fence));
    /* A timeout is an error, never a pixel pass. Exit without destroying
     * potentially pending Vulkan objects if the wait fails. */
    CHECK(vkWaitForFences(device, 1, &fence, VK_TRUE, UINT64_C(5000000000)));
}

static void image_barrier(struct target *t, VkImageLayout old, VkImageLayout next,
                          VkPipelineStageFlags src_stage, VkAccessFlags src_access,
                          VkPipelineStageFlags dst_stage, VkAccessFlags dst_access)
{
    VkImageMemoryBarrier b = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
        .srcAccessMask = src_access, .dstAccessMask = dst_access,
        .oldLayout = old, .newLayout = next,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = t->image,
        .subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 }
    };
    vkCmdPipelineBarrier(cmd, src_stage, dst_stage, 0, 0, NULL, 0, NULL, 1, &b);
}

static void buffer_barrier(struct target *t, VkPipelineStageFlags src_stage,
                           VkAccessFlags src_access, VkPipelineStageFlags dst_stage,
                           VkAccessFlags dst_access)
{
    VkBufferMemoryBarrier b = {
        .sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,
        .srcAccessMask = src_access, .dstAccessMask = dst_access,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .buffer = t->staging, .offset = 0, .size = VK_WHOLE_SIZE
    };
    vkCmdPipelineBarrier(cmd, src_stage, dst_stage, 0, 0, NULL, 1, &b, 0, NULL);
}

static VkBufferImageCopy copy_region(const struct target *t)
{
    /* Zero rowLength/imageHeight means tightly packed. RGBA8, offset zero,
     * full image, mip 0, layer 0; all transfer granularity edges satisfied. */
    return (VkBufferImageCopy) {
        .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 },
        .imageExtent = { t->w, t->h, 1 }
    };
}

static void upload_pattern(struct target *t)
{
    for (uint32_t y = 0; y < t->h; ++y) {
        for (uint32_t x = 0; x < t->w; ++x) {
            uint32_t v = x * UINT32_C(0x9e3779b9) ^ y * UINT32_C(0x85ebca6b);
            v ^= v >> 16; v *= UINT32_C(0x7feb352d); v ^= v >> 15;
            size_t k = ((size_t)y * t->w + x) * 4;
            t->expected[k] = (uint8_t)v;
            t->expected[k + 1] = (uint8_t)(v >> 8);
            t->expected[k + 2] = (uint8_t)(v >> 16);
            t->expected[k + 3] = (uint8_t)(v >> 24);
        }
    }
    memcpy(t->mapped, t->expected, t->bytes);
    /* Entire allocation is mapped: offset 0 and WHOLE_SIZE also work with
     * noncoherent memory, regardless of nonCoherentAtomSize. */
    VkMappedMemoryRange range = {
        .sType = VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE,
        .memory = t->staging_memory, .offset = 0, .size = VK_WHOLE_SIZE
    };
    CHECK(vkFlushMappedMemoryRanges(device, 1, &range));
    begin_commands();
    buffer_barrier(t, VK_PIPELINE_STAGE_HOST_BIT, VK_ACCESS_HOST_WRITE_BIT,
                    VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_READ_BIT);
    image_barrier(t, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
        VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, 0,
        VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_WRITE_BIT);
    VkBufferImageCopy region = copy_region(t);
    vkCmdCopyBufferToImage(cmd, t->staging, t->image,
                          VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);
    image_barrier(t, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
        VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_WRITE_BIT,
        VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, COLOR_ACCESS);
    submit_wait();
}

static uint32_t odd_position(uint32_t limit, uint32_t seed)
{
    /* limit >= 1; choose an odd coordinate in [1, limit]. */
    return 1 + 2 * (seed % ((limit + 1) / 2));
}

static VkRect2D damage(const struct target *t, uint32_t frame, uint32_t pass)
{
    uint32_t w, h, x, y;
    if (pass < 8) {
        w = ((t->w - 4) | 1u); h = 1 + 2 * (pass % 4);
        x = 1; y = odd_position(t->h - h, frame * 139 + pass * 113);
    } else if (pass < 28) {
        w = 1 + 2 * ((pass * 13 + frame * 7) % 97);
        h = 1 + 2 * ((pass * 7 + frame * 11) % 49);
        x = odd_position(t->w - w, pass * 163 + frame * 101);
        y = odd_position(t->h - h, pass * 61 + frame * 173);
    } else {
        /* Larger regions cross several possible GMEM tile boundaries.
         * 63,31 deliberately straddles the 64x32 alignment boundary. */
        w = 1025; h = 513;
        x = pass == 28 ? 63 : odd_position(t->w - w, pass * 83 + frame * 23);
        y = pass == 28 ? 31 : odd_position(t->h - h, pass * 41 + frame * 71);
    }
    return (VkRect2D){ { (int32_t)x, (int32_t)y }, { w, h } };
}

static void pass_pixel(uint8_t pixel[4], uint32_t serial)
{
    uint32_t bits = 1 + serial % 15;
    for (uint32_t c = 0; c < 4; ++c)
        pixel[c] = options.load_clear ? options.load_color[c] :
            options.color_set || options.draw ? options.color[c] :
            (uint8_t)((bits & (1u << c)) ? 255 : 0);
}

static VkClearValue float_color(const uint8_t pixel[4])
{
    VkClearValue value = {0};
    for (uint32_t c = 0; c < 4; ++c)
        value.color.float32[c] = (float)pixel[c] / 255.0f;
    return value;
}

static void expect_rect(struct target *t, VkRect2D r, const uint8_t pixel[4])
{
    for (uint32_t y = (uint32_t)r.offset.y; y < (uint32_t)r.offset.y + r.extent.height; ++y)
        for (uint32_t x = (uint32_t)r.offset.x; x < (uint32_t)r.offset.x + r.extent.width; ++x)
            memcpy(t->expected + ((size_t)y * t->w + x) * 4, pixel, 4);
}

static VkRect2D pass_clear(VkRect2D area, uint32_t pass)
{
    VkRect2D r = area;
    if (pass & 1u) {
        if (r.extent.width > 4) { r.offset.x++; r.extent.width -= 2; }
        if (r.extent.height > 4) { r.offset.y++; r.extent.height -= 2; }
    }
    return r;
}

static void record_pass(struct target *t, VkRect2D area, VkRect2D rect,
                        uint32_t serial)
{
    /* Full-subresource external dependency, including LOAD reads and STORE
     * writes. Readback restores COLOR_ATTACHMENT_OPTIMAL before next use. */
    image_barrier(t, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
        VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
        VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, COLOR_ACCESS,
        VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, COLOR_ACCESS);
    uint8_t pixel[4];
    pass_pixel(pixel, serial);
    VkClearValue value = float_color(pixel);
    VkRenderPassBeginInfo bi = {
        .sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,
        .renderPass = render_pass, .framebuffer = t->framebuffer, .renderArea = area,
        .clearValueCount = options.load_clear ? 1u : 0u,
        .pClearValues = options.load_clear ? &value : NULL
    };
    vkCmdBeginRenderPass(cmd, &bi, VK_SUBPASS_CONTENTS_INLINE);
    if (options.load_clear) {
        expect_rect(t, area, pixel);
    } else if (!options.no_clear) {
        if (options.draw) {
            if (rect.extent.width > props.limits.maxViewportDimensions[0] ||
                rect.extent.height > props.limits.maxViewportDimensions[1] ||
                (float)rect.offset.x < props.limits.viewportBoundsRange[0] ||
                (float)rect.offset.y < props.limits.viewportBoundsRange[0] ||
                (float)((uint32_t)rect.offset.x + rect.extent.width) > props.limits.viewportBoundsRange[1] ||
                (float)((uint32_t)rect.offset.y + rect.extent.height) > props.limits.viewportBoundsRange[1])
                stop("Draw rectangle exceeds viewport limits", 77);
            VkViewport viewport = { (float)rect.offset.x, (float)rect.offset.y,
                (float)rect.extent.width, (float)rect.extent.height, 0.0f, 1.0f };
            vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline);
            vkCmdSetViewport(cmd, 0, 1, &viewport);
            vkCmdSetScissor(cmd, 0, 1, &rect);
            vkCmdPushConstants(cmd, pipeline_layout, VK_SHADER_STAGE_FRAGMENT_BIT,
                               0, sizeof(value.color.float32), value.color.float32);
            /* One pair of oversized fullscreen triangles; blending is off,
             * so their overlap writes the same constant bytes twice. */
            vkCmdDraw(cmd, 6, 1, 0, 0);
        } else {
            VkClearAttachment ca = { .aspectMask = VK_IMAGE_ASPECT_COLOR_BIT,
                .colorAttachment = 0, .clearValue = value };
            VkClearRect cr = { .rect = rect, .baseArrayLayer = 0, .layerCount = 1 };
            vkCmdClearAttachments(cmd, 1, &ca, 1, &cr);
        }
        expect_rect(t, rect, pixel);
    }
    vkCmdEndRenderPass(cmd);
}

static void frame_commands(struct target *t, uint32_t frame)
{
    begin_commands();
    for (uint32_t pass = 0; pass < PASSES; ++pass) {
        VkRect2D area = damage(t, frame, pass);
        record_pass(t, area, pass_clear(area, pass), frame * PASSES + pass);
    }
    submit_wait();
}

static int read_and_compare(struct target *t, int frame)
{
    begin_commands();
    /* Reuse the upload/readback buffer only after previous transfer and
     * host reads complete. Host reads finished before this queue submit. */
    buffer_barrier(t, VK_PIPELINE_STAGE_TRANSFER_BIT | VK_PIPELINE_STAGE_HOST_BIT,
        VK_ACCESS_TRANSFER_READ_BIT | VK_ACCESS_TRANSFER_WRITE_BIT | VK_ACCESS_HOST_READ_BIT,
        VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_WRITE_BIT);
    image_barrier(t, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
        /* Include the upload explicitly for the frame=-1 checkpoint. */
        VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT | VK_PIPELINE_STAGE_TRANSFER_BIT,
        COLOR_ACCESS | VK_ACCESS_TRANSFER_WRITE_BIT,
        VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_READ_BIT);
    VkBufferImageCopy region = copy_region(t);
    vkCmdCopyImageToBuffer(cmd, t->image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                          t->staging, 1, &region);
    buffer_barrier(t, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_WRITE_BIT,
        VK_PIPELINE_STAGE_HOST_BIT, VK_ACCESS_HOST_READ_BIT);
    image_barrier(t, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
        VK_PIPELINE_STAGE_TRANSFER_BIT, VK_ACCESS_TRANSFER_READ_BIT,
        VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, COLOR_ACCESS);
    submit_wait();
    VkMappedMemoryRange range = {
        .sType = VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE,
        .memory = t->staging_memory, .offset = 0, .size = VK_WHOLE_SIZE
    };
    CHECK(vkInvalidateMappedMemoryRanges(device, 1, &range));
    size_t mismatches = 0;
    uint64_t hash = UINT64_C(14695981039346656037);
    for (uint32_t y = 0; y < t->h; ++y) {
        for (uint32_t x = 0; x < t->w; ++x) {
            size_t k = ((size_t)y * t->w + x) * 4;
            const uint8_t *got = t->mapped + k, *want = t->expected + k;
            for (uint32_t c = 0; c < 4; ++c) {
                hash ^= got[c]; hash *= UINT64_C(1099511628211);
            }
            if (memcmp(got, want, 4)) {
                if (mismatches < 8)
                    fprintf(stderr, "%ux%u frame=%d pixel (%u,%u): got %02x%02x%02x%02x expected %02x%02x%02x%02x\n",
                        t->w, t->h, frame, x, y, got[0], got[1], got[2], got[3],
                        want[0], want[1], want[2], want[3]);
                ++mismatches;
            }
        }
    }
    printf("%ux%u frame=%d: %zu/%zu pixels differ; FNV64=%016" PRIx64 "\n",
        t->w, t->h, frame, mismatches, (size_t)t->w * t->h, hash);
    return mismatches ? 1 : 0;
}

static void destroy_target(struct target *t)
{
    /* Last use completed by a successful fence wait. */
    vkDestroyFramebuffer(device, t->framebuffer, NULL);
    vkDestroyImageView(device, t->view, NULL);
    vkDestroyImage(device, t->image, NULL);
    vkFreeMemory(device, t->image_memory, NULL);
    vkUnmapMemory(device, t->staging_memory);
    vkDestroyBuffer(device, t->staging, NULL);
    vkFreeMemory(device, t->staging_memory, NULL);
    free(t->expected);
}

/* Diagnostic values are printed in RGBA byte order, independent of host endian. */
static uint32_t rgba(const uint8_t *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 |
           (uint32_t)p[2] << 8 | p[3];
}

struct bounds { uint32_t x0, y0, x1, y1; size_t n; };

static void include_pixel(struct bounds *b, uint32_t x, uint32_t y)
{
    if (!b->n || x < b->x0) b->x0 = x;
    if (!b->n || y < b->y0) b->y0 = y;
    if (!b->n || x > b->x1) b->x1 = x;
    if (!b->n || y > b->y1) b->y1 = y;
    ++b->n;
}

static int inside(VkRect2D r, uint32_t x, uint32_t y)
{
    return x >= (uint32_t)r.offset.x && y >= (uint32_t)r.offset.y &&
        x - (uint32_t)r.offset.x < r.extent.width &&
        y - (uint32_t)r.offset.y < r.extent.height;
}

static int key_compare(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return (x > y) - (x < y);
}

static int offset_match(const struct target *t, const uint8_t *pre,
                        uint32_t x, uint32_t y, int dx, int dy)
{
    int sx = (int)x + dx, sy = (int)y + dy;
    return sx >= 0 && sy >= 0 && sx < (int)t->w && sy < (int)t->h &&
        !memcmp(t->mapped + ((size_t)y * t->w + x) * 4,
                pre + ((size_t)sy * t->w + (uint32_t)sx) * 4, 4);
}

static int run_matches(const struct target *t, const uint8_t *pre,
                       uint32_t sx, uint32_t sy, const uint8_t *got,
                       uint32_t n, int vertical)
{
    if (vertical ? n > t->h - sy : n > t->w - sx) return 0;
    for (uint32_t i = 0; i < n; ++i) {
        size_t k = ((size_t)(sy + (vertical ? i : 0)) * t->w + sx + (vertical ? 0 : i)) * 4;
        if (memcmp(pre + k, got + (size_t)i * 4, 4)) return 0;
    }
    return 1;
}

static void source_search(const struct target *t, const uint8_t *pre,
                          const char *label, uint32_t gx, uint32_t gy,
                          uint32_t n, int vertical)
{
    const uint8_t *got = t->mapped + ((size_t)gy * t->w + gx) * 4;
    unsigned found = 0;
    printf("source-search %s: got run of %u px", label, n);
    for (uint32_t sy = 0; sy + (vertical ? n : 1) <= t->h; ++sy)
        for (uint32_t sx = 0; sx + (vertical ? 1 : n) <= t->w; ++sx) {
            if (!run_matches(t, pre, sx, sy, got, n, vertical)) continue;
            printf("%s pre(%u,%u) => offset (%d,%d)", found ? ";" : " found at",
                   sx, sy, (int)sx - (int)gx, (int)sy - (int)gy);
            if (++found == 8) goto done;
        }
done:
    if (!found) printf(" not found");
    putchar('\n');
}

static void source_search_variant(const struct target *t, const uint8_t *pre,
                                  const char *label, uint32_t gx, uint32_t gy,
                                  uint32_t n, int bgra)
{
    const uint8_t *got = t->mapped + ((size_t)gy * t->w + gx) * 4;
    uint8_t *variant = allocate((size_t)n * 4);
    for (uint32_t i = 0; i < n; ++i) {
        const uint8_t *p = got + (size_t)i * 4;
        uint8_t *q = variant + (size_t)i * 4;
        if (bgra) { q[0] = p[2]; q[1] = p[1]; q[2] = p[0]; q[3] = p[3]; }
        else { q[0] = p[3]; q[1] = p[2]; q[2] = p[1]; q[3] = p[0]; }
    }
    int found = 0;
    printf("source-search row0 %s: got run of %u px", label, n);
    for (uint32_t sy = 0; sy < t->h && !found; ++sy)
        for (uint32_t sx = 0; sx + n <= t->w; ++sx)
            if (run_matches(t, pre, sx, sy, variant, n, 0)) {
                printf(" found at pre(%u,%u) => offset (%d,%d)\n",
                       sx, sy, (int)sx - (int)gx, (int)sy - (int)gy);
                found = 1;
                break;
            }
    if (!found) printf(" not found\n");
    free(variant);
}

static void dump_source_search(const struct target *t, const uint8_t *pre, VkRect2D area)
{
    uint32_t x = (uint32_t)area.offset.x, y = (uint32_t)area.offset.y;
    uint32_t row_n = area.extent.width < 32 ? area.extent.width : 32;
    uint32_t col_n = area.extent.height < 30 ? area.extent.height : 30;
    uint32_t ys[] = { y, y + (area.extent.height > 1), y + area.extent.height - 1 };
    const char *labels[] = { "row0", "row1", "rowLast" };
    for (unsigned i = 0; i < 3; ++i)
        source_search(t, pre, labels[i], x, ys[i], row_n, 0);
    source_search(t, pre, "col0", x, y, col_n, 1);
    source_search_variant(t, pre, "ABGR", x, y, row_n, 0);
    source_search_variant(t, pre, "BGRA", x, y, row_n, 1);
}

static void print_map(const struct target *t, VkRect2D area,
                      uint32_t cw, uint32_t ch, uint32_t x0, uint32_t y0,
                      uint32_t x1, uint32_t y1)
{
    printf("Map %ux%u pixels/cell; origin cell=(%u,%u); cells=[%u,%u)x[%u,%u); "
           "renderArea cells=[%.2f,%.2f)x[%.2f,%.2f) (absolute); "
           "'.'=0 '#'=all '1'..'9'=ceil(10*wrong/total), capped at 9\n",
           cw, ch, x0, y0, x0, x1, y0, y1,
           (double)area.offset.x / cw,
           ((double)area.offset.x + area.extent.width) / cw,
           (double)area.offset.y / ch,
           ((double)area.offset.y + area.extent.height) / ch);
    for (uint32_t cy = y0; cy < y1; ++cy) {
        for (uint32_t cx = x0; cx < x1; ++cx) {
            uint32_t wrong = 0, total = 0;
            for (uint32_t y = cy * ch; y < (cy + 1) * ch && y < t->h; ++y)
                for (uint32_t x = cx * cw; x < (cx + 1) * cw && x < t->w; ++x) {
                    size_t k = ((size_t)y * t->w + x) * 4;
                    wrong += memcmp(t->mapped + k, t->expected + k, 4) != 0;
                    ++total;
                }
            uint32_t digit = total ? (10 * wrong + total - 1) / total : 0;
            putchar(!wrong ? '.' : wrong == total ? '#' :
                    (int)('0' + (digit > 9 ? 9 : digit)));
        }
        putchar('\n');
    }
}

static void diagnose(const struct target *t, const uint8_t *pre, uint32_t pass,
                     VkRect2D area, VkRect2D rect, uint32_t serial)
{
    uint8_t pixel[4];
    pass_pixel(pixel, serial);
    uint32_t color = rgba(pixel);
    if (options.load_clear || options.no_clear) rect = area;
    printf("First bad pass=%u (zero-based), frame=0; renderArea=(%d,%d %ux%u); "
           "operation=%s: (%d,%d %ux%u), RGBA=%08" PRIx32 "\n",
           pass, area.offset.x, area.offset.y, area.extent.width, area.extent.height,
           options.no_clear ? "LOAD/STORE only" : options.load_clear ? "loadOp CLEAR" :
           options.draw ? "draw" : "clear attachment",
           rect.offset.x, rect.offset.y, rect.extent.width, rect.extent.height, color);
    printf("vkGetRenderAreaGranularity=%ux%u; actual tile grid unknown\n",
           granularity.width, granularity.height);
    struct bounds box[2] = {{0}, {0}}, all = {0};
    for (uint32_t y = 0; y < t->h; ++y)
        for (uint32_t x = 0; x < t->w; ++x) {
            size_t k = ((size_t)y * t->w + x) * 4;
            if (!memcmp(t->mapped + k, t->expected + k, 4)) continue;
            include_pixel(&box[inside(area, x, y) ? 0 : 1], x, y);
            include_pixel(&all, x, y);
        }
    /* A bounded small candidate set, Cartesian combinations including axial
     * offsets. Exclude (0,0); no wrapping at image edges. Positive dx/dy means
     * got(x,y) == pre(x+dx,y+dy). Ratios include out-of-bounds as nonmatches. */
    static const int delta[] = {0, -4, 4, -16, 16, -32, 32, -64, 64, -128, 128};
    printf("Offset candidates: Cartesian {0,+/-4,+/-16,+/-32,+/-64,+/-128}, "
           "excluding (0,0); got(x,y)=pre(x+dx,y+dy); no edge wrapping.\n");
    for (unsigned cls = 0; cls < 2; ++cls) {
        struct bounds b = box[cls];
        printf("%s renderArea: wrong=%zu", cls ? "Outside" : "Inside", b.n);
        if (!b.n) { printf("; bbox=empty; histogram=empty; best offset=n/a\n"); continue; }
        printf("; bbox inclusive=(%u,%u)..(%u,%u)\n", b.x0, b.y0, b.x1, b.y1);
        uint64_t *keys = allocate(b.n * sizeof(*keys));
        size_t used = 0, hits[11][11] = {{0}};
        for (uint32_t y = b.y0; y <= b.y1; ++y)
            for (uint32_t x = b.x0; x <= b.x1; ++x) {
                size_t k = ((size_t)y * t->w + x) * 4;
                if ((inside(area, x, y) ? 0u : 1u) != cls ||
                    !memcmp(t->mapped + k, t->expected + k, 4)) continue;
                keys[used++] = (uint64_t)rgba(t->mapped + k) << 32 | rgba(t->expected + k);
                for (unsigned iy = 0; iy < 11; ++iy)
                    for (unsigned ix = 0; ix < 11; ++ix)
                        if (ix || iy)
                            hits[iy][ix] += (size_t)offset_match(t, pre, x, y, delta[ix], delta[iy]);
            }
        unsigned bx = 1, by = 0;
        for (unsigned iy = 0; iy < 11; ++iy)
            for (unsigned ix = 0; ix < 11; ++ix)
                if ((ix || iy) && hits[iy][ix] > hits[by][bx]) { bx = ix; by = iy; }
        printf("  best offset=(%d,%d): %zu/%zu = %.6f (all wrong pixels; "
               "value correlation, not proof of addressing)\n",
               delta[bx], delta[by], hits[by][bx], b.n, (double)hits[by][bx] / (double)b.n);
        qsort(keys, used, sizeof(*keys), key_compare);
        uint64_t top[8] = {0}; size_t count[8] = {0};
        for (size_t i = 0; i < used;) {
            size_t j = i + 1;
            while (j < used && keys[j] == keys[i]) ++j;
            for (unsigned rank = 0; rank < 8; ++rank)
                if (j - i > count[rank]) {
                    for (unsigned r = 7; r > rank; --r) { top[r] = top[r-1]; count[r] = count[r-1]; }
                    top[rank] = keys[i]; count[rank] = j - i; break;
                }
            i = j;
        }
        free(keys);
        size_t types[4] = {0}, pair_types[8][4] = {{0}};
        for (uint32_t y = b.y0; y <= b.y1; ++y)
            for (uint32_t x = b.x0; x <= b.x1; ++x) {
                size_t k = ((size_t)y * t->w + x) * 4;
                if ((inside(area, x, y) ? 0u : 1u) != cls ||
                    !memcmp(t->mapped + k, t->expected + k, 4)) continue;
                uint32_t got = rgba(t->mapped + k);
                unsigned type = !memcmp(t->mapped + k, pre + k, 4) ? 0 :
                    !options.no_clear && got == color ? 1 : offset_match(t, pre, x, y, delta[bx], delta[by]) ? 2 : 3;
                ++types[type];
                uint64_t key = (uint64_t)got << 32 | rgba(t->expected + k);
                for (unsigned r = 0; r < 8; ++r)
                    if (count[r] && key == top[r]) ++pair_types[r][type];
            }
        printf("  Exclusive classification (priority: same pixel, clear, best offset, other): "
               "not updated=%zu clear=%zu shifted=%zu other/possible garbage=%zu\n",
               types[0], types[1], types[2], types[3]);
        for (unsigned r = 0; r < 8 && count[r]; ++r)
            printf("  got=%08" PRIx32 " expected=%08" PRIx32 " count=%zu: "
                   "not updated=%zu clear=%zu shifted=%zu other=%zu\n",
                   (uint32_t)(top[r] >> 32), (uint32_t)top[r], count[r],
                   pair_types[r][0], pair_types[r][1], pair_types[r][2], pair_types[r][3]);
    }
    if (!all.n) return;
    uint32_t cols = (t->w + 63) / 64, rows = (t->h + 31) / 32;
    uint32_t x0 = all.x0 / 64, y0 = all.y0 / 32;
    uint32_t x1 = all.x1 / 64 + 3, y1 = all.y1 / 32 + 3;
    print_map(t, area, 64, 32, x0 > 2 ? x0 - 2 : 0, y0 > 2 ? y0 - 2 : 0,
              x1 < cols ? x1 : cols, y1 < rows ? y1 : rows);
    x0 = all.x0 / 16; y0 = all.y0 / 4;
    x1 = x0 + 16; y1 = y0 + 16;
    cols = (t->w + 15) / 16; rows = (t->h + 3) / 4;
    printf("Fine window: 256x64 pixels, cell-aligned around mismatch top-left=(%u,%u)\n",
           all.x0, all.y0);
    print_map(t, area, 16, 4, x0, y0, x1 < cols ? x1 : cols, y1 < rows ? y1 : rows);
}

static void dump_pixel(const struct target *t, uint32_t x, uint32_t y)
{
    size_t k = ((size_t)y * t->w + x) * 4;
    const uint8_t *g = t->mapped + k, *e = t->expected + k;
    printf("  (%u,%u) got=%02x %02x %02x %02x expected=%02x %02x %02x %02x\n",
           x, y, g[0], g[1], g[2], g[3], e[0], e[1], e[2], e[3]);
}

static void dump_area(const struct target *t, VkRect2D area)
{
    uint32_t x = (uint32_t)area.offset.x, y = (uint32_t)area.offset.y;
    uint32_t rows[] = { y, y + 1, y + area.extent.height - 1 };
    const char *labels[] = { "first", "second", "last" };
    for (unsigned r = 0; r < 3; ++r) {
        printf("Area %s row (raw RGBA bytes):\n", labels[r]);
        for (uint32_t i = 0; i < 8 && i < area.extent.width; ++i)
            dump_pixel(t, x + i, rows[r]);
    }
    printf("Immediately left: column x-1, first up to 4 area rows:\n");
    if (!x) printf("  unavailable: image left edge\n");
    else for (uint32_t i = 0; i < 4 && i < area.extent.height; ++i)
        dump_pixel(t, x - 1, y + i);
    printf("Immediately above: row y-1, first up to 4 area columns:\n");
    if (!y) printf("  unavailable: image top edge\n");
    else for (uint32_t i = 0; i < 4 && i < area.extent.width; ++i)
        dump_pixel(t, x + i, y - 1);
}

static void argument_color(const char *s, uint8_t pixel[4])
{
    if (strlen(s) != 8) stop("Colour must be exactly eight hex digits RRGGBBAA", 2);
    for (unsigned i = 0; i < 4; ++i) {
        unsigned v = 0;
        for (unsigned j = 0; j < 2; ++j) {
            unsigned char c = (unsigned char)s[2 * i + j];
            unsigned d;
            if (c >= '0' && c <= '9') d = c - '0';
            else if (c >= 'a' && c <= 'f') d = c - 'a' + 10u;
            else if (c >= 'A' && c <= 'F') d = c - 'A' + 10u;
            else stop("Colour must be exactly eight hex digits RRGGBBAA", 2);
            v = v * 16 + d;
        }
        pixel[i] = (uint8_t)v;
    }
}

static uint32_t argument_uint(const char *s)
{
    char *end;
    errno = 0;
    unsigned long v = strtoul(s, &end, 10);
    if (!*s || *s < '0' || *s > '9' || *end || errno || v > UINT32_MAX)
        stop("Arguments must be nonnegative decimal integers", 2);
    return (uint32_t)v;
}

int main(int argc, char **argv)
{
    uint32_t passes = PASSES;
    int diagnostic = 0, single = 0, stop_first = 0;
    VkRect2D single_area = {{0, 0}, {0, 0}};
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--help")) {
            printf("Usage: %s [--passes N [--stop-first] | --single X Y W H [options] [--stop-first]]\n"
                   "--passes: first N passes (1..32), frame 0, 2880x1920, readback each pass.\n"
                   "--single: one pass on fresh 2880x1920 image; clear inset by 1 (W,H >= 3).\n"
                   "Single-only options (order independent):\n"
                   "  --no-clear: LOAD/STORE only, no clear or draw; image unchanged.\n"
                   "  --color RRGGBBAA: clear/draw colour (default ff000000).\n"
                   "  --full-rect: clear/draw rect equals render area.\n"
                   "  --load-clear RRGGBBAA: loadOp CLEAR of entire render area.\n"
                   "  --draw: fullscreen triangle pair, push-constant colour.\n"
                   "  --dump-area: actual/expected RGBA bytes and edge neighbours.\n"
                   "--no-clear, --load-clear, --draw are mutually exclusive.\n"
                   "--color and --full-rect may accompany any operation.\n"
                   "--stop-first alone: all 32 diagnostic passes, stop on first mismatch.\n"
                   "No options: original two-size, three-frame test. Exit: 0/1/2/77.\n", argv[0]);
            return 0;
        } else if (!strcmp(argv[i], "--no-clear")) {
            options.no_clear = 1;
        } else if (!strcmp(argv[i], "--full-rect")) {
            options.full_rect = 1;
        } else if (!strcmp(argv[i], "--draw")) {
            options.draw = 1;
        } else if (!strcmp(argv[i], "--dump-area")) {
            options.dump_area = 1;
        } else if (!strcmp(argv[i], "--color") && i + 1 < argc) {
            argument_color(argv[++i], options.color); options.color_set = 1;
        } else if (!strcmp(argv[i], "--load-clear") && i + 1 < argc) {
            argument_color(argv[++i], options.load_color); options.load_clear = 1;
        } else if (!strcmp(argv[i], "--stop-first")) {
            stop_first = 1;
        } else if (!strcmp(argv[i], "--passes") && i + 1 < argc && !diagnostic) {
            passes = argument_uint(argv[++i]);
            if (!passes || passes > PASSES) stop("--passes must be in 1..32", 2);
            diagnostic = 1;
        } else if (!strcmp(argv[i], "--single") && i + 4 < argc && !diagnostic) {
            uint32_t x = argument_uint(argv[++i]), y = argument_uint(argv[++i]);
            uint32_t w = argument_uint(argv[++i]), h = argument_uint(argv[++i]);
            if (x > 2880 || y > 1920 || w < 3 || h < 3 || w > 2880 - x || h > 1920 - y)
                stop("--single must fit 2880x1920 with W,H >= 3 for inset clear", 2);
            single_area = (VkRect2D){{(int32_t)x, (int32_t)y}, {w, h}};
            single = diagnostic = 1;
            passes = 1;
        } else stop("Invalid options; use --help", 2);
    }
    if (!single && (options.no_clear || options.color_set || options.full_rect ||
                    options.load_clear || options.draw || options.dump_area))
        stop("New probe options require --single", 2);
    if (options.no_clear + options.load_clear + options.draw > 1)
        stop("--no-clear, --load-clear and --draw are mutually exclusive", 2);
    diagnostic |= stop_first;
    struct timespec start, end;
    (void)timespec_get(&start, TIME_UTC);
    const char *debug = getenv("TU_DEBUG");
    if (diagnostic)
        printf("TU_DEBUG=%s; diagnostic: 2880x1920, frame=0, %u passes, "
               "per-pass readback; stop-first=%d",
               debug ? debug : "(unset: autotune, GMEM not guaranteed)", passes, stop_first);
    else
        printf("TU_DEBUG=%s; 2 sizes, %u frames/size, %u partial LOAD/STORE passes/frame\n",
            debug ? debug : "(unset: autotune, GMEM not guaranteed)", FRAMES, PASSES);
    if (single)
        printf("; single=(%d,%d %ux%u); --no-clear=%d --color=%08" PRIx32
               " (explicit=%d) --full-rect=%d --load-clear=%d:%08" PRIx32
               " --draw=%d --dump-area=%d",
               single_area.offset.x, single_area.offset.y,
               single_area.extent.width, single_area.extent.height,
               options.no_clear, rgba(options.color), options.color_set,
               options.full_rect, options.load_clear, rgba(options.load_color),
               options.draw, options.dump_area);
    if (diagnostic) putchar('\n');
    init_vulkan();
    if (options.draw) create_draw_pipeline();
    const uint32_t sizes[2][2] = { {2880, 1920}, {2879, 1919} };
    int failed = 0;
    for (uint32_t i = 0; i < (diagnostic ? 1u : 2u); ++i) {
        struct target t = create_target(sizes[i][0], sizes[i][1]);
        upload_pattern(&t);
        /* Establish that initial upload/readback works before damage. */
        failed |= read_and_compare(&t, -1);
        if (!failed && diagnostic) {
            uint8_t *pre = allocate(t.bytes);
            for (uint32_t pass = 0; pass < passes; ++pass) {
                /* Snapshot actual content, including previous corruption. The
                 * independent expected oracle is never replaced by readback. */
                memcpy(pre, t.mapped, t.bytes);
                VkRect2D area = single ? single_area : damage(&t, 0, pass);
                VkRect2D rect = pass_clear(area, pass);
                if (single && !options.full_rect) {
                    rect.offset.x++; rect.offset.y++;
                    rect.extent.width -= 2; rect.extent.height -= 2;
                }
                begin_commands();
                record_pass(&t, area, rect, pass);
                submit_wait();
                printf("Comparing partial pass=%u (zero-based)\n", pass);
                int bad = read_and_compare(&t, 0);
                if (options.dump_area) {
                    dump_area(&t, area);
                    dump_source_search(&t, pre, area);
                }
                if (bad && !failed) diagnose(&t, pre, pass, area, rect, pass);
                failed |= bad;
                if (bad && stop_first) break;
            }
            free(pre);
        } else if (!failed) {
            for (uint32_t frame = 0; frame < FRAMES; ++frame) {
                frame_commands(&t, frame);
                failed |= read_and_compare(&t, (int)frame);
                if (failed) break; /* Entire failing checkpoint was compared. */
            }
        }
        destroy_target(&t);
        if (failed) break;
    }
    if (pipeline) vkDestroyPipeline(device, pipeline, NULL);
    if (pipeline_layout) vkDestroyPipelineLayout(device, pipeline_layout, NULL);
    vkDestroyRenderPass(device, render_pass, NULL);
    vkDestroyFence(device, fence, NULL);
    vkDestroyCommandPool(device, pool, NULL);
    vkDestroyDevice(device, NULL);
    vkDestroyInstance(instance, NULL);
    (void)timespec_get(&end, TIME_UTC);
    printf("%s; elapsed %.3f s\n", failed ? "FAIL" : "PASS",
        (double)(end.tv_sec - start.tv_sec) + (double)(end.tv_nsec - start.tv_nsec) / 1e9);
    return failed;
}
