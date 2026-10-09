obj-m += spx_front_enable.o

$(obj)/spx_front_enable.o: $(obj)/front-enable.inc
$(obj)/front-enable.inc: $(src)/front-enable.dtso
	dtc -I dts -O dtb -o $(obj)/front-enable.dtbo $<
	python3 -c 'from pathlib import Path; Path("$@").write_text(",".join(str(x) for x in Path("$(obj)/front-enable.dtbo").read_bytes()))'

obj-m += ov5693.o
