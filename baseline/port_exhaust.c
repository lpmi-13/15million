#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char *end = NULL;
    unsigned long long requested = argc == 2 ? strtoull(argv[1], &end, 10) : 0;
    if (argc != 2 || !end || *end || requested < 1 || requested > 15000000) {
        fprintf(stderr, "usage: port_exhaust MAX_LISTENERS (1..15000000)\n");
        return 2;
    }
    unsigned low = 0, high = 0;
    FILE *range = fopen("/proc/sys/net/ipv4/ip_local_port_range", "r");
    if (!range || fscanf(range, "%u %u", &low, &high) != 2 || high < low) {
        perror("ip_local_port_range"); return 1;
    }
    fclose(range);
    size_t capacity = (size_t)(high - low + 1) + 1024;
    if (capacity > 64000) capacity = 64000;
    struct rlimit limit;
    if (getrlimit(RLIMIT_NOFILE, &limit) < 0) { perror("getrlimit"); return 1; }
    rlim_t needed = capacity + 32;
    if (limit.rlim_cur < needed) {
        limit.rlim_cur = limit.rlim_max < needed ? limit.rlim_max : needed;
        if (setrlimit(RLIMIT_NOFILE, &limit) < 0) { perror("setrlimit"); return 1; }
    }
    if (limit.rlim_cur < needed) {
        fprintf(stderr, "RLIMIT_NOFILE is too low for port exhaustion\n"); return 2;
    }
    int *fds = calloc(capacity, sizeof(int));
    if (!fds) { perror("calloc"); return 1; }
    size_t count = 0;
    int failed_errno = 0;
    const char *syscall_name = "none";
    while (count < requested) {
        if (count == capacity) {
            fprintf(stderr, "the descriptor array filled before ports ran out\n");
            break;
        }
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) { failed_errno = errno; syscall_name = "socket"; break; }
        if (listen(fd, 1) < 0) {
            failed_errno = errno;
            syscall_name = "listen";
            close(fd);
            break;
        }
        fds[count++] = fd;
    }
    if (failed_errno == EADDRINUSE) fprintf(stderr, "listen: Address already in use\n");
    printf("{\"range_low\":%u,\"range_high\":%u,\"count\":%zu,"
           "\"maximum\":%zu,\"failed_syscall\":\"%s\",\"errno\":%d}\n",
           low, high, count, (size_t)requested, syscall_name, failed_errno);
    fflush(stdout);
    for (size_t index = 0; index < count; index++) close(fds[index]);
    free(fds);
    return 1;
}
