#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <assert.h>
#include <pthread.h>
#include <sys/resource.h>
#include <unistd.h>

static void *check_thread(void *arg) {
    uintptr_t tp;
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(tp));
    uintptr_t *words = (uintptr_t *)tp;
    uintptr_t slot_app = words[2]; // TLS_SLOT_APP at offset 0x10 (word 2)
    printf("Thread %ld: tp=%p, TLS_SLOT_APP [offset 0x10]=%p\n", (long)gettid(), (void *)tp, (void *)slot_app);
    assert(slot_app == 0); // Must be free and zero initially
    return NULL;
}

int main(void) {
    uintptr_t tp;
    __asm__ volatile("mrs %0, tpidr_el0" : "=r"(tp));
    uintptr_t *words = (uintptr_t *)tp;
    printf("Main thread %ld: tp=%p, TLS_SLOT_APP [offset 0x10]=%p\n", (long)gettid(), (void *)tp, (void *)words[2]);

    pthread_t th;
    assert(pthread_create(&th, NULL, check_thread, NULL) == 0);
    assert(pthread_join(th, NULL) == 0);

    struct rlimit rl;
    if (getrlimit(RLIMIT_NICE, &rl) == 0) {
        printf("RLIMIT_NICE: cur=%lu, max=%lu\n", (unsigned long)rl.rlim_cur, (unsigned long)rl.rlim_max);
    }

    printf("DEVICE BIONIC VERIFICATION: SUCCESS\n");
    return 0;
}
