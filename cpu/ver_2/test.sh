#!/bin/bash

for var in {1..400}
do
	echo "benchmark$var" | tee -a output.log
	./obj/main ../../../benchmark/benchmark$var.cnf | tee -a output.log
done
