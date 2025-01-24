#ifndef _DISPLAY_EPD_W21_SPI_
#define _DISPLAY_EPD_W21_SPI_
#include "Arduino.h"

#define BUSY_Pin 9
#define RES_Pin 10
#define DC_Pin 11
#define CS_Pin 8

//IO settings
//SCK--GPIO23(SCLK)
//SDIN---GPIO18(MOSI)
#define isEPD_W21_BUSY digitalRead(BUSY_Pin)  //BUSY
#define EPD_W21_RST_0 digitalWrite(RES_Pin,LOW)  //RES
#define EPD_W21_RST_1 digitalWrite(RES_Pin,HIGH)
#define EPD_W21_DC_0  digitalWrite(DC_Pin,LOW) //DC
#define EPD_W21_DC_1  digitalWrite(DC_Pin,HIGH)
#define EPD_W21_CS_0 digitalWrite(CS_Pin,LOW) //CS
#define EPD_W21_CS_1 digitalWrite(CS_Pin,HIGH)

void SPI_Write(unsigned char value);
void EPD_W21_WriteDATA(unsigned char datas);
void EPD_W21_WriteCMD(unsigned char command);


#endif 