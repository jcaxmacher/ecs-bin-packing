import sys
import binpacking

with open('task-memory.txt', 'r') as f:
    mems = f.readlines()

mems = [int(m.strip()) for m in mems]
bins = binpacking.to_constant_volume(mems, int(sys.argv[1]))
print(f'{len(bins)} instances needed')
