# Taking and restoring checkpoints in gem5 + SST

This readme contains the progress of checkpointing in gem5 + SST setup.

## Status of the bridge

The bridge only works with timing mode.
It is inherited from SimObject.

## Code

```sh
git clone git@github.com:kaustav-goswami/gem5.git
# checkout `kg/sst-checkpoints` branch
```

## Approach

1. Currently, we take checkpoint using a gem5 only setup with a local and a remote memory.
2. The address ranges have to be modified when restoring the checkpoint's physical memory.
3. The `m5.cpt` file has to be modified to remove the non-existent SimObjects (this has to be corrected ASAP (see TODO section.))
4. We manually read and write the physical memory file.

## Taking a checkpoint

```sh
# inside the gem5 directory
build/ALL/gem5.opt disaggregated_memory/configs/checkpoints/arm-gem5-take-ckpt.py
# The checkpoint will be created in `gem5-ckpt` directory.
```

## Restoring the checkpoint in SST

1. First we need to modify the `m5.cpt` file.
    Do not restore the final `physmem` so modify the following line from `nbr_of_stores=9` to `nbr_of_stores=8`
2. 


## TODO Items in the short time

1. Make the `OutgoingRequestBridge` inherit from `AbstractMemory` instead of `SimObject`.
2. Make 