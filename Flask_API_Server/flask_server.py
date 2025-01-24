from datetime import datetime, time as datetime_time, timedelta
import time
import uuid
from flask import Flask, Response, render_template, request, jsonify, send_from_directory
from image_helper import apply_floyd_steinberg_dithering, default_color_palette
import os
from PIL import Image
import io
from immich_helper import ImmichHelper, ImmichScaleMode
from flask_socketio import SocketIO, emit
import threading
import socket
from pathlib import Path
import json
import requests  # Add this at the top with other imports
import atexit

###########
# GLOBALS #
###########

BROADCAST_PORT = 9998
DEVICE_RESPONSE_PORT = 9999
HTTP_SERVER_PORT = 9999
DEVICES_FILE = './config/devices.json'
Path('./config').mkdir(exist_ok=True)

CONFIG_FILE = './config/config.json'
DEFAULT_CONFIG = {
    'wakeup_interval': 60,
    'rotation': 0,
    'enhanced': 1.0,
    'contrast': 1.0
}

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()

def save_config(config):
    Path(CONFIG_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

config = load_config()

app = Flask(__name__, static_folder='static', template_folder='templates')
socketio = SocketIO(app)
immich = ImmichHelper(
    url=os.getenv('IMMICH_URL', 'http://localhost'),
    image_path=os.getenv('IMAGE_PATH', './images'),
    api_key=os.getenv('IMMICH_API_KEY'),
    config=config
)

active_transfers = {}
devices = {}
groups = {}

def load_devices():
    """Load devices from file"""
    try:
        with open(DEVICES_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_devices():
    """Save devices to file"""
    with open(DEVICES_FILE, 'w') as f:
        json.dump(devices, f, indent=4)

# Load devices at startup
devices = load_devices()

# Register save function to run on exit
atexit.register(save_devices)

# Function to get the local IP address
def get_local_ip():
    """Get the local IP address that can reach the network"""
    try:
        # Try getting all network interfaces and their addresses
        import netifaces
        interfaces = netifaces.interfaces()
        for interface in interfaces:
            addrs = netifaces.ifaddresses(interface)
            if (netifaces.AF_INET in addrs):
                for addr in addrs[netifaces.AF_INET]:
                    ip = addr['addr']
                    if not ip.startswith('127.'):  # Skip localhost
                        print(f"Found IP address {ip} on interface {interface}")
                        return ip
    except:
        # Fallback method
        try:
            temp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            temp_socket.connect(("8.8.8.8", 80))
            local_ip = temp_socket.getsockname()[0]
            temp_socket.close()
            print(f"Found IP address {local_ip} using fallback method")
            return local_ip
        except Exception as e:
            print(f"Error in fallback IP detection: {e}")
            return socket.gethostbyname(socket.gethostname())

# Add device cleanup task
def cleanup_disconnected_devices():
    while True:
        try:
            current_time = datetime.now()
            for device_id in list(devices.keys()):
                device = devices[device_id]
                last_seen = datetime.fromisoformat(device.get('last_seen', '2000-01-01T00:00:00'))
                
                # Mark device as inactive if not seen for 2 minutes
                if current_time - last_seen > timedelta(minutes=2):
                    device['active'] = False
                    socketio.emit('device_update', devices)
                
                # Only remove device if not seen for 30 days
                if current_time - last_seen > timedelta(days=30):
                    del devices[device_id]
                    socketio.emit('device_update', devices)
                    print(f"Removed device inactive for 30 days: {device_id}")
        except Exception as e:
            print(f"Error in cleanup task: {str(e)}")
        finally:
            time.sleep(60)  # Run cleanup every minute

# Start the cleanup task
threading.Thread(target=cleanup_disconnected_devices, daemon=True).start()

def broadcast_server_presence():
    """Broadcasts server presence on the network"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    
    server_ip = get_local_ip()
    
    message = json.dumps({
        'type': 'SERVER_BROADCAST',
        'server_ip': server_ip,
        'server_port': HTTP_SERVER_PORT
    })
    
    while True:
        try:
            sock.sendto(message.encode(), ('255.255.255.255', BROADCAST_PORT))
            time.sleep(10)
        except Exception as e:
            print(f"Error broadcasting server presence: {e}")
            time.sleep(1)

################
# FLASK SERVER #
################

@app.route('/device-log', methods=['POST'])
def device_log():
    try:
        data = request.get_json()
        print(f"Received log data: {data}")  # Debug print to see what we're receiving
        
        # Validate required fields that match ESP32's log_message format
        if not all(key in data for key in ['message', 'level', 'device_id']):
            print(f"Missing required fields. Received fields: {list(data.keys())}")
            return jsonify({'error': 'Missing required fields (message, level, device_id)'}), 400
            
        # Format log message similar to ESP32's format
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{data['device_id']}] [{data['level']}] {data['message']}"
        
        # Print to console
        print(log_entry)
        
        # Update device's last_seen time since we got a message from it
        if data['device_id'] in devices:
            devices[data['device_id']]['last_seen'] = datetime.now().isoformat()
            save_devices()
            
        return jsonify({'status': 'ok'})
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {str(e)}")
        return jsonify({'error': 'Invalid JSON format'}), 400
    except Exception as e:
        print(f"Error processing log message: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/wakeup-interval', methods=['GET'])
def wakeup_interval():
    return jsonify(interval=config['wakeup_interval'] * 60)  # Convert minutes to seconds

@app.route('/init-transfer', methods=['POST'])
def init_transfer():
    try:
        print("\n=== Init Transfer Request ===")
        data = request.get_json()
        device_id = data.get('device_id')
        
        print(f"Request from IP: {request.remote_addr}")
        print(f"Device ID: {device_id}")
        print(f"Headers: {dict(request.headers)}")
        print(f"Current devices: {devices}")
        
        if not device_id:
            print("Error: Missing device ID")
            return jsonify({'error': 'Missing device ID'}), 400
            
        if device_id not in devices:
            print(f"Error: Unknown device ID: {device_id}")
            print("Known devices:", list(devices.keys()))
            return jsonify({'error': f'Unknown device ID: {device_id}'}), 400

        device = devices[device_id]
        print(f"Found device: {device}")
        
        # Update last seen time
        device['last_seen'] = datetime.now().isoformat()
        device['active'] = True
        save_devices()

        # Validate group assignment
        group_id = device.get('group_id')
        if not group_id or group_id not in groups:
            print(f"Error: Device not in group. Device: {device_id}, Group: {group_id}")
            return jsonify({'error': 'Device not assigned to a group'}), 400

        group = groups[group_id]
        album_id = group.get('album')  # Note: This is now correctly an album ID
        if not album_id:
            print(f"Error: Group has no album. Group: {group_id}")
            return jsonify({'error': 'Group has no album assigned'}), 400

        print(f"Using album: {album_id} for group: {group_id}")

        # Use device specs stored during registration
        try:
            image_id, image_bytes = immich.get_random_image(
                group_id=group_id,
                album_id=album_id,  # Changed from album_name to album_id
                width=device['width'],
                height=device['height'], 
                scale_mode=ImmichScaleMode.CROP
            )
        except Exception as e:
            print(f"Error retrieving image: {str(e)}")
            return jsonify({'error': str(e)}), 500

        # Convert bytes to image for dithering
        img = Image.open(io.BytesIO(image_bytes))
        dithered = apply_floyd_steinberg_dithering(img)
        
        # Convert to single channel using palette
        img_bytes = bytearray()
        for y in range(device['height']):
            for x in range(device['width']):
                rgb = dithered.getpixel((x, y))
                color_code = default_color_palette.get(tuple(rgb), 0xFF)
                img_bytes.append(color_code)
                
        img_bytes = bytes(img_bytes)
        
        # Use buffer size from device registration
        buffer_size = device['buffer_size']
        if len(img_bytes) % buffer_size != 0:
            return jsonify({
                'error': 'Buffer size must be multiple of image size',
                'image_size': len(img_bytes),
                'buffer_size': buffer_size
            }), 400
            
        transfer_id = str(uuid.uuid4())
        active_transfers[transfer_id] = {
            'image_data': img_bytes,
            'total_chunks': len(img_bytes) // buffer_size,
            'buffer_size': buffer_size,
            'sent_chunks': 0
        }

        return jsonify({
            'transfer_id': transfer_id,
            'total_chunks': active_transfers[transfer_id]['total_chunks'],
            'image_size': len(img_bytes)
        })
        
    except Exception as e:
        print(f"Error during transfer initialization: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/get-chunk/<transfer_id>/<int:chunk_index>', methods=['GET'])
def get_chunk(transfer_id, chunk_index):
    global active_transfers
    try:
        print(f"[{datetime.now()}] Chunk request: ID={transfer_id}, index={chunk_index}")

        if transfer_id not in active_transfers:
            print(f"[{datetime.now()}] Error: Invalid transfer ID: {transfer_id}")
            return jsonify({'error': 'Invalid or expired transfer ID'}), 404
            
        transfer = active_transfers[transfer_id]
        
        if chunk_index >= transfer['total_chunks']:
            print(f"[{datetime.now()}] Error: Chunk index out of range: {chunk_index}")
            return jsonify({'error': 'Chunk index out of range'}), 400    
            
        start_idx = chunk_index * transfer['buffer_size']
        end_idx = start_idx + transfer['buffer_size']
        chunk = transfer['image_data'][start_idx:end_idx]
        
        # Update sent chunks count
        transfer['sent_chunks'] += 1
        print(f"[{datetime.now()}] Sent chunk {chunk_index}/{transfer['total_chunks']-1} "
              f"for transfer {transfer_id}")
        
        # Clean up if transfer is complete
        if transfer['sent_chunks'] == transfer['total_chunks']:
            del active_transfers[transfer_id]
            
        return Response(chunk, mimetype='application/octet-stream')
        
    except Exception as e:
        print(f"[{datetime.now()}] Error serving chunk: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/groups', methods=['GET', 'POST'])
def manage_groups():
    if request.method == 'GET':
        return jsonify(groups)
    elif request.method == 'POST':
        data = request.get_json()
        group_id = str(uuid.uuid4())
        group_data = {
            'name': data['name'],
            'album': None,
            'random': True,
            'created_at': datetime.now().isoformat()
        }
        groups[group_id] = group_data
        
        # Create group directory and config
        group_config_path = Path(f'./config/groups/{group_id}.json')
        group_config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(group_config_path, 'w') as f:
            json.dump(group_data, f, indent=4)
        
        return jsonify({'group_id': group_id})

def validate_device_groups():
    """Ensure all devices have valid group assignments"""
    changes_made = False
    for device_id, device in devices.items():
        if 'group_id' in device and device['group_id'] is not None:
            if device['group_id'] not in groups:
                print(f"Removing invalid group assignment for device {device_id}")
                device.pop('group_id', None)
                changes_made = True
    
    if changes_made:
        save_devices()
        socketio.emit('device_update', devices)

@app.route('/groups/<group_id>', methods=['GET', 'PUT', 'DELETE'])
def manage_group(group_id):
    if request.method == 'GET':
        if group_id in groups:
            return jsonify(groups[group_id])
        return jsonify({'error': 'Group not found'}), 404
    elif request.method == 'PUT':
        data = request.get_json()
        groups[group_id].update(data)
        # Update group configuration file
        group_config_path = Path(f'./config/groups/{group_id}.json')
        with open(group_config_path, 'w') as f:
            json.dump(groups[group_id], f, indent=4)
        return jsonify({'status': 'updated'})
    elif request.method == 'DELETE':
        # Remove group assignment from all devices in this group
        for device_id, device in devices.items():
            if device.get('group_id') == group_id:
                device.pop('group_id', None)
        save_devices()
        socketio.emit('device_update', devices)  # Notify clients about device updates
        
        # Delete the group
        del groups[group_id]
        group_config_path = Path(f'./config/groups/{group_id}.json')
        if group_config_path.exists():
            group_config_path.unlink()
        return jsonify({'status': 'deleted'})

@app.route('/devices', methods=['GET'])
def get_devices():
    return jsonify(devices)

@app.route('/devices/<device_id>/group', methods=['PUT'])
def assign_device_to_group(device_id):
    try:
        if device_id not in devices:
            return jsonify({'error': 'Device not found'}), 404

        data = request.get_json()
        group_id = data.get('group_id')
        was_assigned = data.get('was_assigned', False)
        
        if group_id is None:
            # Remove device from group
            devices[device_id].pop('group_id', None)
        else:
            # Verify group exists before assigning
            if group_id not in groups:
                return jsonify({'error': 'Group not found'}), 404
            # Assign device to group
            devices[device_id]['group_id'] = group_id
            
        # Update was_assigned flag
        if was_assigned:
            devices[device_id]['was_assigned'] = True
            
        save_devices()  # Save after group assignment
        socketio.emit('device_update', devices)  # Broadcast update to all clients
        return jsonify({'status': 'updated'})
    except Exception as e:
        print(f"Error in assign_device_to_group: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/devices/<device_id>', methods=['GET'])
def get_device_info(device_id):
    device = devices.get(device_id)
    if device:
        return jsonify(device)
    else:
        return jsonify({'error': 'Device not found'}), 404

@app.route('/immich-status', methods=['GET'])
def immich_status():
    try:
        url = f"{os.getenv('IMMICH_URL', 'http://localhost')}/api/albums"
        response = requests.get(url, headers=immich._get_headers(), timeout=5)
        response.raise_for_status()
        albums = response.json()
        return jsonify({
            'server': os.getenv('IMMICH_URL', 'http://localhost'),
            'connected': True,
            'albums': len(albums),
            'config': config
        })
    except Exception as e:
        return jsonify({
            'server': os.getenv('IMMICH_URL', 'http://localhost'),
            'connected': False,
            'albums': 0,
            'config': config
        })

@app.route('/groups/<group_id>/devices', methods=['GET'])
def get_group_devices(group_id):
    group_devices = []
    for device_id, device in devices.items():
        if device.get('group_id') == group_id:
            # Include the device_id in the device info
            device_info = device.copy()
            device_info['device_id'] = device_id
            group_devices.append(device_info)
    return jsonify(group_devices)

@app.route('/albums', methods=['GET'])
def get_albums():
    try:
        url = f"{immich.config['immich']['url']}/api/albums"
        response = requests.get(url, headers=immich._get_headers())
        response.raise_for_status()
        albums = [
            {
                'id': album['id'],
                'albumName': album['albumName']  # Make sure we're sending the album name
            }
            for album in response.json()
        ]
        return jsonify(albums)
    except Exception as e:
        print(f"Error fetching albums: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Add new endpoint for device registration
@app.route('/device-register', methods=['POST'])
def device_register():
    try:
        device_info = request.get_json()
        if 'device_id' not in device_info:
            return jsonify({'error': 'Missing device ID'}), 400
            
        device_id = device_info['device_id']
        print(f"Registering device: {device_id}")  # Debug print
        
        # Add registration time if device is new
        if device_id not in devices:
            device_info['first_seen'] = datetime.now().isoformat()
            
        # Update device info
        device_info['last_seen'] = datetime.now().isoformat()
        device_info['active'] = True  # Device is currently awake
        
        # Preserve group assignment if it exists
        if device_id in devices and 'group_id' in devices[device_id]:
            device_info['group_id'] = devices[device_id]['group_id']
        
        devices[device_id] = device_info
        save_devices()  # Save after each registration
        print(f"Current devices: {devices}")  # Debug print
        
        # Use emit instead of socketio.emit for more reliable broadcasting
        with app.app_context():
            emit('device_update', devices, broadcast=True, namespace='/')
        
        return jsonify({'status': 'registered'})
        
    except Exception as e:
        print(f"Error in device registration: {str(e)}")  # Debug print
        return jsonify({'error': str(e)}), 500

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/config', methods=['PUT'])
def update_config():
    try:
        new_config = request.get_json()
        config.update(new_config)
        save_config(config)
        immich.update_config(config)
        return jsonify({'status': 'updated'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Add function to load saved groups
def load_groups():
    """Load groups from config files"""
    groups_dir = Path('./config/groups')
    if not groups_dir.exists():
        return {}
        
    loaded_groups = {}
    for group_file in groups_dir.glob('*.json'):
        try:
            group_id = group_file.stem
            with open(group_file, 'r') as f:
                group_data = json.load(f)
                loaded_groups[group_id] = group_data
        except Exception as e:
            print(f"Error loading group {group_file}: {e}")
    return loaded_groups

# Load both devices and groups at startup
devices = load_devices()
groups = load_groups()
validate_device_groups()  # Add this line after loading both devices and groups

@app.route('/groups/<group_id>/album-tracking/<album_id>', methods=['GET'])
def get_album_tracking(group_id, album_id):
    """Get tracking info for a group's album"""
    try:
        tracker = immich._get_group_tracker(group_id)
        if not tracker:
            return jsonify({'error': 'Group not found'}), 404

        # Get all assets for the album
        url = f"{immich.config['immich']['url']}/api/albums/{album_id}"
        response = requests.get(url, headers=immich._get_headers())
        response.raise_for_status()
        
        album_data = response.json()
        total_count = len(album_data['assets'])
        shown_count = len(tracker.get_tracked_ids())

        return jsonify({
            'total_count': total_count,
            'shown_count': shown_count
        })
    except Exception as e:
        print(f"Error getting album tracking: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/groups/<group_id>/album-tracking/<album_id>/reset', methods=['POST'])
def reset_album_tracking(group_id, album_id):
    """Reset tracking for a group's album"""
    try:
        tracker = immich._get_group_tracker(group_id)
        if not tracker:
            return jsonify({'error': 'Group not found'}), 404

        tracker.reset_tracking()
        return jsonify({'status': 'reset successful'})
    except Exception as e:
        print(f"Error resetting album tracking: {str(e)}")
        return jsonify({'error': str(e)}), 500

########
# MAIN #
########

# Run the Flask server
if __name__ == '__main__':
    threading.Thread(target=broadcast_server_presence, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=HTTP_SERVER_PORT, allow_unsafe_werkzeug=True)
