#include <stdlib.h>
#include "jerryscript-port.h"

void jerry_port_fatal (jerry_fatal_code_t code)
{
  (void) code;
//  volatile int *p = (int*)0x1;
//  *p = 1; 
  abort();
}

