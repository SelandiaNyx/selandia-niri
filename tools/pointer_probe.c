/* Test-only virtual pointer, built with the upstream wlr protocol XML.
 * Refuses normal desktop sessions; smoke.py supplies a private state directory.
 * Usage: pointer-probe x y output-width output-height [click]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include "wlr-virtual-pointer-client.h"

static struct zwlr_virtual_pointer_manager_v1 *manager;
static void global(void *data, struct wl_registry *registry, uint32_t name,
                   const char *interface, uint32_t version) {
    (void)data;
    if (!strcmp(interface, "zwlr_virtual_pointer_manager_v1"))
        manager = wl_registry_bind(registry, name, &zwlr_virtual_pointer_manager_v1_interface,
                                   version < 2 ? version : 2);
}
static void removed(void *data, struct wl_registry *registry, uint32_t name) {
    (void)data; (void)registry; (void)name;
}
static const struct wl_registry_listener listener = {global, removed};

int main(int argc, char **argv) {
    const char *private = getenv("SELANDIA_PRIVATE_PROBE");
    const char *state = getenv("XDG_STATE_HOME");
    const char *name = state ? strrchr(state, '/') : NULL;
    if (!private || strcmp(private, "1") || !name || strncmp(name + 1, "selandia-smoke-", 15)) {
        fprintf(stderr, "Only run inside smoke.py's isolated desktop.\n"); return 2;
    }
    if (argc != 5 && argc != 6) return 2;
    int x = atoi(argv[1]), y = atoi(argv[2]), width = atoi(argv[3]), height = atoi(argv[4]);
    if (x < 0 || y < 0 || width < 1 || height < 1 || x >= width || y >= height) return 2;
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) return 3;
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &listener, NULL);
    wl_display_roundtrip(display);
    if (!manager) { fprintf(stderr, "Virtual pointer protocol unavailable\n"); return 77; }
    struct zwlr_virtual_pointer_v1 *pointer = zwlr_virtual_pointer_manager_v1_create_virtual_pointer(manager, NULL);
    struct timespec time;
    clock_gettime(CLOCK_MONOTONIC, &time);
    uint32_t now = time.tv_sec * 1000 + time.tv_nsec / 1000000;
    zwlr_virtual_pointer_v1_motion_absolute(pointer, now, x, y, width, height);
    zwlr_virtual_pointer_v1_frame(pointer);
    wl_display_roundtrip(display);
    if (argc == 6) {
        usleep(100000);
        zwlr_virtual_pointer_v1_button(pointer, now + 100, 0x110, WL_POINTER_BUTTON_STATE_PRESSED);
        zwlr_virtual_pointer_v1_frame(pointer);
        wl_display_roundtrip(display);
        usleep(100000);
        zwlr_virtual_pointer_v1_button(pointer, now + 200, 0x110, WL_POINTER_BUTTON_STATE_RELEASED);
        zwlr_virtual_pointer_v1_frame(pointer);
        wl_display_roundtrip(display);
    }
    zwlr_virtual_pointer_v1_destroy(pointer);
    zwlr_virtual_pointer_manager_v1_destroy(manager);
    wl_registry_destroy(registry);
    wl_display_flush(display);
    wl_display_disconnect(display);
    return 0;
}
