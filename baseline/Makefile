CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Werror -std=c11
BIN = bin/webserver_libc bin/bound_server bin/port_exhaust bin/socket_cost

.PHONY: all clean
all: $(BIN)

bin:
	mkdir -p bin

bin/%: %.c | bin
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(BIN)
