# Build the gem5 SGX enclave test program.
#
# The program uses inline-assembly m5 pseudo-ops, so it does NOT need libm5.
# A statically-linked binary is produced so it can be dropped onto any guest
# disk image and run without worrying about the guest's shared libraries.
#
#   make            # build a static x86-64 binary
#   make dynamic    # build a normal dynamically-linked binary
#   make clean

CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra -std=gnu11
TARGET   = sgx_enclave_test
SRC      = sgx_enclave_test.c

.PHONY: all static dynamic clean

all: static

static: $(SRC)
	$(CC) $(CFLAGS) -static -o $(TARGET) $(SRC)

dynamic: $(SRC)
	$(CC) $(CFLAGS) -o $(TARGET) $(SRC)

clean:
	rm -f $(TARGET)
