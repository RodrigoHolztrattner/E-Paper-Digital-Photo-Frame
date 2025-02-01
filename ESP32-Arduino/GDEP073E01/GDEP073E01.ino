#include <SPI.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "Display_EPD_W21_spi.h"
#include "Display_EPD_W21.h"
#include <WiFiUdp.h>

// NOTE: Code partially taken from https://github.com/0015/7-Color-E-Paper-Digital-Photo-Frame/tree/main

/////////////
// DEFINES //
/////////////

#define S_To_uS_Factor 1000000ULL      //Conversion factor for micro seconds to seconds 

// Server endpoints
#define DEVICE_REGISTER_ENDPOINT "/device-register"
#define INIT_IMAGE_TRANSFER_ENDPOINT "/init-transfer"
#define GET_IMAGE_CHUNK_ENDPOINT "/get-chunk"
#define GET_IMAGE_ENDPOINT "/get-img-data"
#define GET_WAKEUP_INTERVAL "/wakeup-interval"
#define LOG_ENDPOINT "/device-log"

#define BYTES_PER_PIXEL 1

#define BROADCAST_PORT 9998       // Broadcast port
#define BROADCAST_TIMEOUT 60000   // Broadcast mode timeout in milliseconds

// Deep sleep intervals (in seconds)
#define SLEEP_INTERVAL_SHORT 60     // 1 minute
#define SLEEP_INTERVAL_MEDIUM 300   // 5 minutes
#define SLEEP_INTERVAL_LONG 3600    // 1 hour
#define SLEEP_INTERVAL_DEFAULT SLEEP_INTERVAL_LONG

// RGB LED color definitions
#define RGB_OFF 0
#define RGB_RED 1
#define RGB_GREEN 2
#define RGB_BLUE 3
#define RGB_YELLOW 4
#define RGB_MAGENTA 5
#define RGB_CYAN 6
#define RGB_WHITE 7

/////////////
// STRUCTS //
/////////////

enum LogLevel 
{
    LOG_DEBUG,
    LOG_INFO,
    LOG_WARNING,
    LOG_ERROR
};

struct HttpResponse 
{
    bool success;      // true if status code is 2xx
    int status_code;   // HTTP status code
    String response;   // Response body
};

/////////////
// GLOBALS //
/////////////

WiFiUDP  s_udp;
String   s_server_ip               = "";
bool     s_is_connected_to_server  = false;
bool     s_is_broadcasting_enabled = false;
uint16_t s_server_port             = 0;

const char*    s_wifi_ssid        = "Deviceland"; // Your WiFi SSID
const char*    s_wifi_password    = "Nina001122"; // Your WiFi Password
const uint32_t s_wifi_retry_count = 10;           // Number of times to retry connecting to WiFi

uint32_t       g_buffer_size  = 0;
uint32_t       g_free_heap    = 0;
const uint32_t g_width        = EPD_WIDTH;
const uint32_t g_height       = EPD_HEIGHT;
const uint8_t  g_palette_size = 7;

void set_rgb_led(uint8_t color, uint32_t duration_ms = 0, uint32_t loops = 1, uint32_t loop_duration_off_ms = -1);
void log_message(const char* message, LogLevel level = LOG_INFO);

///////////
// SETUP //
///////////

void setup() 
{
    Serial.begin(115200);  // Add Serial initialization
    pinMode(BUSY_Pin, INPUT);  //BUSY
    pinMode(RES_Pin, OUTPUT); //RES 
    pinMode(DC_Pin, OUTPUT); //DC   
    pinMode(CS_Pin, OUTPUT); //CS   

    set_rgb_led(RGB_BLUE); // Notify startup

    //SPI
    SPI.beginTransaction(SPISettings(10000000, MSBFIRST, SPI_MODE0)); 
    SPI.begin ();  

    set_rgb_led(RGB_BLUE, 100, 3); // Notify SPI success
}

//////////
// LOOP //
//////////

void loop() 
{
    /*
    * Main loop is executed whenever hibernation finishes (when the ESP32 wakes up from deep sleep).
    * It's intention is to connect to WIFI, connect to the server, and then attempt to update the display image.
    * If any of these steps fail, the ESP32 will go back to deep sleep to conserve power.
    */

    int sleep_interval = SLEEP_INTERVAL_DEFAULT;

    set_rgb_led(RGB_YELLOW, 50, 5, 20); // Notify entering main loop

    // No need to blink red as the connection function already does that
    if(connect_wifi())
    {
        if (enter_broadcast_mode())
        {
            String transferId;
            uint32_t totalChunks;

            // Fetch the wakeup interval
            sleep_interval = fetch_wakeup_interval();

            if (init_image_transfer(transferId, totalChunks)) 
            {
                if (fetch_image_chunks(transferId, totalChunks)) 
                {
                    log_message("Image transfer successful, all tasks succeeded", LOG_INFO);
                    set_rgb_led(RGB_BLUE, 50, 3);
                    set_rgb_led(RGB_GREEN, 50, 3);
                }
                else
                {
                    log_message("Failed to fetch chunks", LOG_ERROR);

                    // Use a lower sleep interval if the image transfer failed, because the server confirmed
                    // connection with the image provider (otherwise, the init request would have failed), and
                    // something else happened while transfering the image chunks.
                    sleep_interval = SLEEP_INTERVAL_MEDIUM;
                }
            }
            else
            {
                log_message("Failed to initialize transfer", LOG_ERROR);

                // Use a moderate sleep interval if the image transfer init failed, as this could be just a temporary
                // issue communicating with the image provider.
                sleep_interval = SLEEP_INTERVAL_MEDIUM;
            }
        }
    }

    hibernate(sleep_interval);
}

//////////////////
// GENERIC HTTP //
//////////////////

HttpResponse http_post(const char* endpoint, const char* payload, uint32_t timeout_ms = 5000) 
{
    if (s_server_ip == "" || s_server_port == 0) return {false, 0, ""};

    HTTPClient http;
    http.begin("http://" + s_server_ip + ":" + String(s_server_port) + endpoint);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(timeout_ms);

    HttpResponse result;
    int httpCode = http.POST(payload);
    result.status_code = httpCode;
    result.success = httpCode >= 200 && httpCode < 300;
    
    if (result.success) 
    {
        result.response = http.getString();
    }
    else if(s_is_connected_to_server)
    {
        char msg[64];
        snprintf(msg, sizeof(msg), "HTTP request failed: %s", http.errorToString(httpCode).c_str());
        Serial.println(msg);
    }
    
    http.end();
    return result;
}

HttpResponse http_get(const char* endpoint) 
{
    if (s_server_ip == "" || s_server_port == 0) return {false, 0, ""};

    HTTPClient http;
    http.begin("http://" + s_server_ip + ":" + String(s_server_port) + endpoint);
    
    HttpResponse result;
    int httpCode = http.GET();
    result.status_code = httpCode;
    result.success = httpCode >= 200 && httpCode < 300;
    
    if (result.success) 
    {
        result.response = http.getString();
    }
    else if (s_is_connected_to_server)
    {
        char msg[64];
        snprintf(msg, sizeof(msg), "HTTP GET failed: %s", http.errorToString(httpCode).c_str());
        Serial.println(msg);
    }
    
    http.end();
    return result;
}

/////////////
// HELPERS //
/////////////

void set_rgb_led(uint8_t color, uint32_t duration_ms, uint32_t loops, uint32_t loop_duration_off_ms) 
{
    rgbLedWrite(RGB_BUILTIN,0,0,0);

    for(int i=0; i<loops; i++)
    {
        switch(color) 
        {
            case RGB_RED:
                rgbLedWrite(RGB_BUILTIN,255,0,0); // Red
                break;
            case RGB_GREEN:
                rgbLedWrite(RGB_BUILTIN,0,255,0); // Green
                break;
            case RGB_BLUE:
                rgbLedWrite(RGB_BUILTIN,0,0,255); // Blue
                break;
            case RGB_YELLOW:
                rgbLedWrite(RGB_BUILTIN,255,255,0); // Yellow
                break;
            case RGB_MAGENTA:
                rgbLedWrite(RGB_BUILTIN,255,0,255); // Magenta
                break;
            case RGB_CYAN:
                rgbLedWrite(RGB_BUILTIN,0,255,255); // Cyan
                break;
            case RGB_WHITE:
                rgbLedWrite(RGB_BUILTIN,255,255,255); // White
                break;
        }
        
        if (duration_ms > 0) 
        {
            delay(duration_ms);
            rgbLedWrite(RGB_BUILTIN,0,0,0); // Turn off after delay
        }

        if(loop_duration_off_ms != 0)
        {
            delay(loop_duration_off_ms != -1 ? loop_duration_off_ms : duration_ms);
        }
    }
}

String get_device_id() 
{
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char deviceId[13];
  sprintf(deviceId, "%02X%02X%02X%02X%02X%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  return String(deviceId);
}

const char* log_level_to_string(LogLevel level) 
{
    switch(level) 
    {
        case LOG_DEBUG:   return "DEBUG";
        case LOG_INFO:    return "INFO";
        case LOG_WARNING: return "WARNING";
        case LOG_ERROR:   return "ERROR";
        default:          return "UNKNOWN";
    }
}

String escape_json_string(const char* str) 
{
    String result;
    while (*str) 
    {
        char c = *str++;
        switch (c) 
        {
            case '\"': result += "\\\""; break;
            case '\\': result += "\\\\"; break;
            case '\b': result += "\\b"; break;
            case '\f': result += "\\f"; break;
            case '\n': result += "\\n"; break;
            case '\r': result += "\\r"; break;
            case '\t': result += "\\t"; break;
            default:
                if (c < 32) 
                {
                    char hex[7];
                    snprintf(hex, sizeof(hex), "\\u%04x", c);
                    result += hex;
                } 
                else 
                {
                    result += c;
                }
        }
    }
    
    return result;
}

void log_message(const char* message, LogLevel level) 
{
    // Format message for serial output
    char formatted_message[256];
    snprintf(formatted_message, sizeof(formatted_message),
             "[%s] [%s] %s",
             get_device_id().c_str(), log_level_to_string(level), message);
             
    // Always print to Serial
    Serial.println(formatted_message);
    
    // Only attempt server communication if connected to backend
    if (s_is_connected_to_server)
    {
        String escaped_message = escape_json_string(message);
        char payload[512];  // Increased buffer size to accommodate escaped characters
        snprintf(payload, sizeof(payload),
                 "{\"message\":\"%s\",\"level\":\"%s\",\"device_id\":\"%s\"}",
                 escaped_message.c_str(), log_level_to_string(level), get_device_id().c_str());
                 
        http_post(LOG_ENDPOINT, payload);
    }
}

bool connect_wifi() 
{
    set_rgb_led(RGB_MAGENTA, 150, 3, 50); // Notify connect wifi mode

    // If already connected, just return
    if (WiFi.status() == WL_CONNECTED)
    {
        set_rgb_led(RGB_GREEN, 1000); // Notify WIFI already connected
        return true;
    }

    int retryCount = 0;
    WiFi.mode(WIFI_STA);   // Set WiFi to station mode
    WiFi.begin(s_wifi_ssid, s_wifi_password);

    // Attempt to connect for a set number of retries
    while (WiFi.status() != WL_CONNECTED && retryCount < s_wifi_retry_count) 
    {
        set_rgb_led(RGB_RED, 100, 3);
        delay(1000);
        log_message("Connecting to WiFi...", LOG_INFO);

        retryCount++;
    }

    if (WiFi.status() == WL_CONNECTED) 
    {
        set_rgb_led(RGB_BLUE, 1000); // Notify WIFI success
        log_message("Connected to WiFi!", LOG_INFO);
        return true;
    } 

    log_message("Failed to connect to WiFi after 10 attempts, stopping WiFi.", LOG_ERROR);
    set_rgb_led(RGB_RED, 300, 3);
    return false;
}

void cleanup()
{
    set_rgb_led(RGB_OFF);  // Ensure LED is off before sleep
    WiFi.disconnect(true); // Disconnect from any connection attempt
    WiFi.mode(WIFI_OFF);   // Turn off the WiFi
    s_server_ip               = "";
    s_server_port             = 0;
    s_is_broadcasting_enabled = false;
    s_is_connected_to_server  = false;

    // Reset status variables
    g_buffer_size = 0;
    g_free_heap = 0;
}

void hibernate(int interval) 
{
    uint64_t sleep_time = interval * S_To_uS_Factor;
    
    // Log actual microseconds for debugging
    char msg[64];
    snprintf(msg, sizeof(msg), "Setting sleep timer for %llu microseconds", sleep_time);
    log_message(msg, LOG_INFO);

    cleanup();

    delay(1000);
    
    esp_sleep_enable_timer_wakeup(sleep_time);
    esp_deep_sleep_start();
}

uint32_t calculate_optimal_image_buffer_size() 
{
    // Calculate total image size (single channel)
    const uint32_t IMAGE_WIDTH      = EPD_WIDTH;
    const uint32_t IMAGE_HEIGHT     = EPD_HEIGHT;
    const uint32_t TOTAL_IMAGE_SIZE = IMAGE_WIDTH * IMAGE_HEIGHT;
    
    // Get available heap and use 30% for buffer
    uint32_t freeHeap = ESP.getFreeHeap();
    uint32_t maxBuffer = (freeHeap * 0.3);
    
    // Ensure buffer is at least one line
    if (maxBuffer < IMAGE_WIDTH) 
    {
        log_message("Warning: Very low memory, using minimum buffer size", LOG_WARNING);
        return IMAGE_WIDTH;
    }
    
    // Calculate how many complete lines fit in the buffer
    uint32_t lines = maxBuffer / IMAGE_WIDTH;
    
    // Ensure the buffer size is a multiple of the total image size
    uint32_t bufferSize = lines * IMAGE_WIDTH;
    if (TOTAL_IMAGE_SIZE % bufferSize != 0) 
    {
        // Adjust lines down until we get a perfect divisor
        while (lines > 0 && TOTAL_IMAGE_SIZE % (lines * IMAGE_WIDTH) != 0) 
        {
            lines--;
        }
        if (lines == 0) 
        {
            // If we couldn't find a perfect divisor, use one line
            lines = 1;
        }
        bufferSize = lines * IMAGE_WIDTH;
    }
    
    char logMsg[64];
    snprintf(logMsg, sizeof(logMsg), "Buffer size: %d bytes (%d lines)", 
             bufferSize, lines);
    log_message(logMsg, LOG_DEBUG);
    
    return bufferSize;
}

////////////////////
// MAIN FUNCTIONS //
////////////////////

bool init_image_transfer(String& transferId, uint32_t& totalChunks) 
{
    set_rgb_led(RGB_MAGENTA, 150, 3, 50); // Notify init image transfer mode

    // Create JSON payload with device ID
    char payload[128];
    const String deviceId = get_device_id();
    snprintf(payload, sizeof(payload), 
             "{\"device_id\":\"%s\"}", 
             deviceId.c_str());
    
    HttpResponse response = http_post(INIT_IMAGE_TRANSFER_ENDPOINT, payload, 30000);
    
    // First check if request was successful
    if (!response.success) {
        char logMsg[128];
        snprintf(logMsg, sizeof(logMsg), "HTTP request failed with code %d", response.status_code);
        log_message(logMsg, LOG_ERROR);
        if (response.response.length() > 0) {
            log_message(response.response.c_str(), LOG_ERROR);
        }
        set_rgb_led(RGB_RED, 300, 3);
        return false;
    }
    
    // Then try to parse JSON response
    StaticJsonDocument<512> doc;
    DeserializationError error = deserializeJson(doc, response.response);
    
    if (error) {
        char logMsg[128];
        snprintf(logMsg, sizeof(logMsg), "JSON parse error: %s", error.c_str());
        log_message(logMsg, LOG_ERROR);
        set_rgb_led(RGB_RED, 300, 3);
        return false;
    }
    
    // Check if response contains an error message
    if (doc.containsKey("error")) {
        const char* errorMsg = doc["error"];
        log_message("Server error: ", LOG_ERROR);
        log_message(errorMsg, LOG_ERROR);
        set_rgb_led(RGB_RED, 300, 3);
        return false;
    }
    
    // Only proceed if we have the required fields
    if (!doc.containsKey("transfer_id") || !doc.containsKey("total_chunks")) {
        log_message("Missing required fields in response", LOG_ERROR);
        set_rgb_led(RGB_RED, 300, 3);
        return false;
    }
    
    transferId = doc["transfer_id"].as<String>();
    totalChunks = doc["total_chunks"].as<uint32_t>();
    set_rgb_led(RGB_BLUE, 1000); // Notify success
    return true;
}

bool fetch_image_chunks(const String& transferId, uint32_t totalChunks) 
{
    set_rgb_led(RGB_MAGENTA, 150, 3, 50); // Notify fetch image chunks mode

    // Use stored buffer size instead of calculating again
    if(g_buffer_size == 0)
    {
        log_message("No buffer size available", LOG_ERROR);
        return false;
    }

    uint8_t* buffer = (uint8_t*)malloc(g_buffer_size);
    uint32_t currentLine = 0;

    if (!buffer) 
    {
        log_message("Failed to allocate buffer for image chunks", LOG_ERROR);
        set_rgb_led(RGB_RED, 300, 3); // Notify failure
        return false;
    }

    PIC_display_Clear();

    EPD_init_fast();
    // EPD_init(); // TODO: Determine if this should be used instead

    // Initialize display update
    PIC_PARTIAL_display_begin();
    
    bool did_error = false;
    for (uint32_t i = 0; i < totalChunks; i++) 
    {
        char endpoint[128];
        snprintf(endpoint, sizeof(endpoint), 
                "%s/%s/%d", GET_IMAGE_CHUNK_ENDPOINT, transferId.c_str(), i);
        
        // Include port in URL
        HTTPClient http;
        String url = "http://" + s_server_ip + ":" + String(s_server_port) + endpoint;
        http.begin(url);
        
        // Fetch chunk
        int httpCode = http.GET();
        
        if (httpCode <= 0) 
        {
            log_message("Failed to get image chunk", LOG_ERROR);
            did_error = true;
            http.end();
            break;
        }
        
        // Get the payload as binary data
        int len = http.getStream().readBytes(buffer, g_buffer_size);
        if (len != g_buffer_size) 
        {
            char logMsg[64];
            snprintf(logMsg, sizeof(logMsg), "Received wrong amount of bytes from the server: Expected: %d bytes | Received: %d bytes", 
                    g_buffer_size, len);
            log_message(logMsg, LOG_ERROR);
            did_error = true;
            http.end();
            break;
        }
        
        if(did_error)
        {
            break;
        }    

        // Process each line in the buffer
        uint32_t processedBytes = 0;
        while (processedBytes < len) 
        {
            // Display one line at a time
            PIC_PARTIAL_display_line(buffer + processedBytes, currentLine);
            processedBytes += EPD_WIDTH * BYTES_PER_PIXEL;  // Advance by full line
            currentLine++;
            
            if (currentLine > EPD_HEIGHT) 
            {
                log_message("Reached end of display", LOG_WARNING);
                did_error = true;
                break;
            }
        }

        http.end();

        if(did_error)
        {
            break;
        }
    }

    // Complete display update
    PIC_PARTIAL_display_end();

    EPD_sleep();
    // EPD_deep_sleep(); // TODO: See the function definition and determine how to enable deep sleep (and if it should be performed here)
    
    free(buffer);

    if(did_error)
    {
        set_rgb_led(RGB_RED, 300, 3); // Notify failure
        return false;
    }
    else
    {
        set_rgb_led(RGB_BLUE, 1000); // Notify success
        return true;
    }
}

void download_image_data() 
{
    HTTPClient http;

    if (!http.begin("http://" + s_server_ip + GET_IMAGE_ENDPOINT)) 
    {
        // Serial.println("Failed to initialize HTTP connection");
        return;
    }

    // Make the request
    int httpResponseCode = http.GET();

    if (httpResponseCode > 0 && httpResponseCode == HTTP_CODE_OK) 
    {
        EPD_init();
        String payload = http.getString();

        // Count the number of elements based on commas in the payload
        int elementCount = 1;
        for (int i = 0; i < payload.length(); i++) 
        {
            if (payload[i] == ',') elementCount++;
        }

        EPD_Display_red();
        delay(5000);

        // Allocate memory for single line
        uint8_t* lineBuffer = (uint8_t*)malloc(EPD_WIDTH);
        if (lineBuffer == nullptr) 
        {
            EPD_Display_Yellow();
            delay(5000);
            EPD_sleep();
            return;
        }

        // EPD_init_fast(); // TODO: Determine if this should be used instead
        // EPD_init();

        EPD_Display_Black();
        delay(5000);

        // Initialize display update
        PIC_PARTIAL_display_begin();

        // Process data line by line
        int currentLine = 0;
        int bufferIndex = 0;
        int startPos = 0;

        for (int i = 0; i < payload.length(); i++) 
        {
            if (payload[i] == ',' || i == payload.length() - 1) 
            {
                // Get the substring for the current hex value
                String hexValue = payload.substring(startPos, i);
                hexValue.trim();

                // Store byte in line buffer
                lineBuffer[bufferIndex++] = (uint8_t)strtol(hexValue.c_str(), nullptr, 16);
                
                // If line buffer is full, display it
                if (bufferIndex >= EPD_WIDTH) 
                {
                    PIC_PARTIAL_display_line(lineBuffer, currentLine);
                    currentLine++;
                    bufferIndex = 0;
                }
                
                startPos = i + 1;
            }
        }

        // Complete display update
        PIC_PARTIAL_display_end();

        EPD_sleep();
        // EPD_deep_sleep(); // TODO: See the function definition and determine how to enable deep sleep (and if it should be performed here)

        delay(5000); // TODO: Remove this, not sure if really necessary

        free(lineBuffer);
        lineBuffer = nullptr;
    } 
    else 
    {
        EPD_init();
        EPD_Display_Green();
        delay(5000); //Delay for 5s.
        EPD_sleep();
        Serial.printf("HTTP GET request failed, error: %s\n", http.errorToString(httpResponseCode).c_str());
    }

    http.end();  // Close connection
}

int fetch_wakeup_interval() 
{
    HttpResponse response = http_get(GET_WAKEUP_INTERVAL);
    
    if (!response.success) 
    {
        log_message("Failed to fetch wakeup interval", LOG_ERROR);
        return SLEEP_INTERVAL_DEFAULT;
    }
    
    StaticJsonDocument<64> doc;
    DeserializationError error = deserializeJson(doc, response.response);
    
    if (error) 
    {
        log_message("Failed to parse wakeup interval response", LOG_ERROR);
        return SLEEP_INTERVAL_DEFAULT;
    }
    
    if (!doc.containsKey("interval")) 
    {
        log_message("Wakeup interval response missing interval field", LOG_ERROR);
        return SLEEP_INTERVAL_DEFAULT;
    }
    
    return doc["interval"].as<int>();
}

void broadcast_task(void *parameter) 
{
    char recv_buffer[256];

    if(!s_udp.begin(BROADCAST_PORT))
    {
        log_message("Failed to start UDP broadcast", LOG_ERROR);
        set_rgb_led(RGB_RED, 300, 3); // Notify failure
        vTaskDelete(NULL);
        return;
    }
    
    set_rgb_led(RGB_WHITE);
    
    while (s_is_broadcasting_enabled && !s_is_connected_to_server) 
    {
        delay(25);
        
        int packetSize = s_udp.parsePacket();
        if(!packetSize) continue;

        int len = s_udp.read(recv_buffer, 255);
        if(len <= 0) continue;

        recv_buffer[len] = '\0';
        
        StaticJsonDocument<200> doc;
        DeserializationError error = deserializeJson(doc, recv_buffer);
        if (error || doc["type"] != "SERVER_BROADCAST") continue;

        s_server_ip = doc["server_ip"].as<String>();
        s_server_port = doc["server_port"].as<uint16_t>();
        
        if (s_server_ip.length() == 0 || s_server_port == 0) continue;
    
        // Calculate and store device info
        g_buffer_size = calculate_optimal_image_buffer_size();
        g_free_heap = ESP.getFreeHeap();
        
        // Send device registration via HTTP
        char payload[256];
        snprintf(payload, sizeof(payload),
                "{\"device_id\":\"%s\",\"name\":\"%s\",\"width\":%d,\"height\":%d,"
                "\"dithering_palette_size\":%d,\"buffer_size\":%d,\"free_space\":%d}",
                get_device_id().c_str(), "ESP32 Device", g_width, g_height, g_palette_size, 
                g_buffer_size, g_free_heap);
        
        HttpResponse response = http_post(DEVICE_REGISTER_ENDPOINT, payload);
        if (response.success) 
        {
            set_rgb_led(RGB_BLUE, 30, 3);
            s_is_connected_to_server = true;
            break;
        }
    }
    
    s_udp.stop();
    vTaskDelete(NULL);
}

bool enter_broadcast_mode() 
{
    set_rgb_led(RGB_MAGENTA, 150, 3, 50); // Notify broadcast mode

    if(s_is_connected_to_server)
    {
        set_rgb_led(RGB_GREEN, 1000); // Notify already connected
        return true;
    }

    log_message("Entering broadcast mode", LOG_INFO);
    set_rgb_led(RGB_MAGENTA, 150, 3, 50); // Notify entering broadcast mode

    // Create a thread to broadcast device information periodically
    s_is_broadcasting_enabled = true;
    xTaskCreate(
        broadcast_task,   // Function to be called
        "BroadcastTask",  // Name of the task
        4096,             // Stack size (bytes)
        NULL,             // Parameter to pass
        1,                // Task priority
        NULL              // Task handle
    );

    unsigned long start_time = millis();
    while (millis() - start_time < BROADCAST_TIMEOUT && !s_is_connected_to_server) 
    {
        delay(1000);
    }

    s_is_broadcasting_enabled = false;
    if(s_is_connected_to_server)
    {
        log_message("Connected to backend, exiting broadcast mode", LOG_INFO);
        set_rgb_led(RGB_BLUE, 1000); // Notify success
        return true;
    }
    else
    {
        log_message("Broadcast mode timeout, entering deep sleep soon", LOG_ERROR);
        set_rgb_led(RGB_RED, 300, 3); // Notify failure
        return false;
    }
}