# Offline only: no installation, firmware loading or hardware invocation.
OUT ?= /var/tmp/spx-cdsp-workload
HEXAGON_CC ?= clang
HEXAGON_LD ?= ld.lld
HOST_CC ?= cc
PYTHON ?= python3

DSP_FLAGS = --target=hexagon-unknown-elf -mcpu=hexagonv66 -G0 -O2 \
	-ffreestanding -fno-builtin -fno-stack-protector \
	-fno-unwind-tables -fno-asynchronous-unwind-tables \
	-fPIC -fvisibility=hidden -Wall -Wextra -Werror

.PHONY: all check inspect
all: $(OUT)/libspx_workload_skel.so

$(OUT):
	mkdir -p "$@"

$(OUT)/workload.o: workload.c | $(OUT)
	$(HEXAGON_CC) $(DSP_FLAGS) -c "$<" -o "$@"

$(OUT)/libspx_workload_skel.so: $(OUT)/workload.o
	$(HEXAGON_LD) -shared --hash-style=sysv --no-undefined \
		-soname libspx_workload_skel.so "$<" -o "$@"

$(OUT)/native.so: workload.c | $(OUT)
	$(HOST_CC) -O2 -shared -fPIC -ffreestanding -fno-builtin \
		-fvisibility=hidden -Wall -Wextra -Werror "$<" -o "$@"

check: $(OUT)/native.so
	$(PYTHON) check_native.py "$(OUT)/native.so"

inspect: all
	readelf -h -d -r --dyn-syms "$(OUT)/libspx_workload_skel.so"
