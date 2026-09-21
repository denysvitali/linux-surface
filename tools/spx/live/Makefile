# Out-of-tree modules for the running known-good kernel.
# Build: make -C tools/spx/live
# Load:  sudo insmod tools/spx/live/spx_usc_observe.ko
# These are not installed over /lib/modules and are not part of the boot path.
#
# The 6.18 build tree's Module.symvers does not list the Surface Aggregator
# exports this module calls. ssam.symvers is generated from the installed
# module. CONFIG_MODVERSIONS is off on that kernel, so the CRC is zero.

KDIR ?= /lib/modules/$(shell uname -r)/build
SSAM_KO ?= /lib/modules/$(shell uname -r)/kernel/drivers/platform/surface/aggregator/surface_aggregator.ko

obj-m += spx_usc_observe.o

all: ssam.symvers
	$(MAKE) -C $(KDIR) M=$(CURDIR) KBUILD_EXTRA_SYMBOLS=$(CURDIR)/ssam.symvers modules

ssam.symvers: $(SSAM_KO)
	nm -g --defined-only $< | awk '$$2 == "T" && ($$3 ~ /^ssam_/ || $$3 ~ /^__ssam_/) { printf "0x00000000\t%s\tsurface_aggregator\tEXPORT_SYMBOL_GPL\t\n", $$3 }' > $@

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
	rm -f ssam.symvers

.PHONY: all clean
