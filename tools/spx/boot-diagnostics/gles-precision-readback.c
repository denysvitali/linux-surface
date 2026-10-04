/* SPDX-License-Identifier: GPL-2.0-only */
/* Offscreen GLES precision diagnostic. No display nodes, modesetting or DRM master.
 * Run separately after the frozen AX workload and return have been collected.
 * This is a diagnostic, not a replacement for the original glmark2 validator.
 */
#define _POSIX_C_SOURCE 200809L
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <gbm.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void require(int ok, const char *what)
{
    if (!ok) {
        fprintf(stderr, "%s failed (EGL 0x%x, GL 0x%x)\n", what,
                eglGetError(), glGetError());
        exit(1);
    }
}

static GLuint shader(GLenum type, const char *source)
{
    GLuint s = glCreateShader(type);
    GLint ok;
    glShaderSource(s, 1, &source, NULL);
    glCompileShader(s);
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[4096];
        glGetShaderInfoLog(s, sizeof(log), NULL, log);
        fprintf(stderr, "Shader compile log: %s\n", log);
    }
    require(ok, "shader compile");
    return s;
}

static void readback(const char *precision, int steps)
{
    const char *vertex = "#version 100\nattribute vec2 position;\n"
        "void main() { gl_Position = vec4(position, 0.0, 1.0); }\n";
    char fragment[4096];
    int n = snprintf(fragment, sizeof(fragment),
        "#version 100\nprecision %s float;\nvoid main() {\n"
        "highp vec2 FragCoord = gl_FragCoord.xy;\n"
        "float d = fract(FragCoord.x * FragCoord.y * 0.0001);\n", precision);
    require(n > 0 && (size_t)n < sizeof(fragment), "fragment formatting");
    for (int i = 0; i < steps; i++) {
        int written = snprintf(fragment + n, sizeof(fragment) - (size_t)n,
            "if (d >= 0.5) d = fract(2.0 * d); else d = fract(3.0 * d);\n");
        require(written > 0 && (size_t)written < sizeof(fragment) - (size_t)n,
                "fragment step formatting");
        n += written;
    }
    int written = snprintf(fragment + n, sizeof(fragment) - (size_t)n,
                           "gl_FragColor = vec4(d, d, d, 1.0); }\n");
    require(written > 0 && (size_t)written < sizeof(fragment) - (size_t)n,
            "fragment output formatting");
    GLuint vs = shader(GL_VERTEX_SHADER, vertex), fs = shader(GL_FRAGMENT_SHADER, fragment);
    GLuint program = glCreateProgram();
    GLint ok;
    glAttachShader(program, vs);
    glAttachShader(program, fs);
    glBindAttribLocation(program, 0, "position");
    glLinkProgram(program);
    glGetProgramiv(program, GL_LINK_STATUS, &ok);
    require(ok, "program link");
    glUseProgram(program);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glFinish();
    GLubyte rgba[4];
    glReadPixels(293, 89, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    require(glGetError() == GL_NO_ERROR, "render/readback");
    printf("    {\"precision\":\"%s\",\"steps\":%d,\"rgba\":[%u,%u,%u,%u]}%s\n",
           precision, steps, rgba[0], rgba[1], rgba[2], rgba[3],
           !strcmp(precision, "highp") && steps == 5 ? "" : ",");
    glDeleteProgram(program);
    glDeleteShader(vs);
    glDeleteShader(fs);
}

int main(void)
{
    require(geteuid() != 0, "unprivileged execution");
    int fd = open("/dev/dri/renderD128", O_RDWR | O_CLOEXEC);
    require(fd >= 0, "renderD128 open");
    struct gbm_device *gbm = gbm_create_device(fd);
    require(gbm != NULL, "GBM device");
    PFNEGLGETPLATFORMDISPLAYEXTPROC get_display =
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    require(get_display != NULL, "EGL platform entry point");
    EGLDisplay display = get_display(EGL_PLATFORM_GBM_KHR, gbm, NULL);
    EGLint major, minor;
    require(display != EGL_NO_DISPLAY && eglInitialize(display, &major, &minor), "EGL initialize");
    const char *extensions = eglQueryString(display, EGL_EXTENSIONS);
    require(extensions && strstr(extensions, "EGL_KHR_surfaceless_context"), "surfaceless context support");
    require(eglBindAPI(EGL_OPENGL_ES_API), "GLES API");
    const EGLint attributes[] = {EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
                                EGL_SURFACE_TYPE, 0, EGL_NONE};
    EGLConfig config;
    EGLint configs;
    require(eglChooseConfig(display, attributes, &config, 1, &configs) && configs == 1,
            "EGL config");
    const EGLint context_attributes[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attributes);
    require(context != EGL_NO_CONTEXT, "GLES3 context");
    require(eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, context), "make current");
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    require(renderer && !strcmp(renderer, "FD680"), "FD680 renderer identity");
    GLuint fbo, color, buffer;
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glGenRenderbuffers(1, &color);
    glBindRenderbuffer(GL_RENDERBUFFER, color);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, 800, 600);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, color);
    require(glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE, "RGBA8 framebuffer");
    glViewport(0, 0, 800, 600);
    glDisable(GL_DITHER);
    const GLfloat triangle[] = {-1, -1, 3, -1, -1, 3};
    glGenBuffers(1, &buffer);
    glBindBuffer(GL_ARRAY_BUFFER, buffer);
    glBufferData(GL_ARRAY_BUFFER, sizeof(triangle), triangle, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, NULL);
    glEnableVertexAttribArray(0);
    GLint range[2], precision;
    glGetShaderPrecisionFormat(GL_FRAGMENT_SHADER, GL_MEDIUM_FLOAT, range, &precision);
    printf("{\n  \"renderer\":\"%s\",\n  \"gl_version\":\"%s\",\n"
           "  \"egl_version\":[%d,%d],\n  \"render_node\":\"/dev/dri/renderD128\",\n"
           "  \"size\":[800,600],\n  \"read_pixel\":[293,89],\n"
           "  \"medium_float_range\":[%d,%d],\n  \"medium_float_precision\":%d,\n"
           "  \"dither_enabled\":false,\n  \"hardware_acceptance_closed\":false,\n"
           "  \"samples\":[\n", renderer, glGetString(GL_VERSION), major, minor,
           range[0], range[1], precision);
    for (int p = 0; p < 2; p++)
        for (int steps = 0; steps <= 5; steps++)
            readback(p ? "highp" : "mediump", steps);
    puts("  ]\n}");
    glDeleteBuffers(1, &buffer);
    glDeleteRenderbuffers(1, &color);
    glDeleteFramebuffers(1, &fbo);
    eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroyContext(display, context);
    eglTerminate(display);
    gbm_device_destroy(gbm);
    close(fd);
    return 0;
}
