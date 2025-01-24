const socket = io();

socket.on('connect', () => {
    console.log('Connected to WebSocket');
    loadInitialState(); // Reload state when reconnecting
});

socket.on('device_update', (devices) => {
    console.log('Received device update:', devices); // Debug log
    updateDeviceList(devices);
});

// Create separate function to update device list
function updateDeviceList(devices) {
    const deviceList = document.getElementById('devices');
    const autoGroupSelect = document.getElementById('auto-group');
    const assignAllBtn = document.getElementById('assign-all-btn');
    
    if (!deviceList) {
        console.error('Device list element not found');
        return;
    }
    
    deviceList.innerHTML = '';
    let hasUnassignedDevices = false;
    
    for (const deviceId in devices) {
        const device = devices[deviceId];
        // Only show devices that aren't in a group
        if (!device.group_id) {
            hasUnassignedDevices = true;
            const li = document.createElement('li');
            const status = device.active ? '🟢' : '💤';
            
            li.textContent = `${status} ${device.name || deviceId} (${device.ip})`;
            li.dataset.deviceId = deviceId;
            li.draggable = true;
            li.addEventListener('dragstart', handleDragStart);
            li.addEventListener('mouseover', () => showDeviceInfo(device));
            
            // Auto-assign if device is newly discovered
            if (!device.was_assigned && autoGroupSelect.value !== 'none') {
                assignDeviceToGroup(deviceId, autoGroupSelect.value);
                continue; // Skip adding to unassigned list
            }
            
            deviceList.appendChild(li);
        }
    }

    // Show/hide assign all button based on unassigned devices
    assignAllBtn.classList.toggle('hidden', !hasUnassignedDevices || autoGroupSelect.value === 'none');

    // Make the unassigned devices list droppable
    deviceList.addEventListener('dragover', handleDragOver);
    deviceList.addEventListener('drop', handleDrop);
}

function assignDeviceToGroup(deviceId, groupId) {
    fetch(`/devices/${deviceId}/group`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ 
            group_id: groupId,
            was_assigned: true // Mark that this device has been assigned before
        })
    }).then(response => {
        if (!response.ok) throw new Error('Failed to assign device to group');
        return response.json();
    }).then(() => {
        fetchGroupDevices(groupId);
        fetch('/devices')
            .then(response => response.json())
            .then(deviceData => {
                devices = deviceData;
                updateDeviceList(devices);
            });
    }).catch(error => {
        console.error('Error assigning device to group:', error);
    });
}

// Add the Assign All button handler
document.getElementById('assign-all-btn').addEventListener('click', () => {
    const groupId = document.getElementById('auto-group').value;
    if (groupId === 'none') return;
    
    const deviceList = document.getElementById('devices');
    const deviceElements = deviceList.getElementsByTagName('li');
    
    Array.from(deviceElements).forEach(deviceEl => {
        assignDeviceToGroup(deviceEl.dataset.deviceId, groupId);
    });
});

// Update auto-group select handler
document.getElementById('auto-group').addEventListener('change', (event) => {
    const assignAllBtn = document.getElementById('assign-all-btn');
    assignAllBtn.classList.toggle('hidden', event.target.value === 'none');
});

function fetchGroupDevices(groupId) {
    fetch(`/groups/${groupId}/devices`)
        .then(response => response.json())
        .then(devices => {
            const groupDevices = document.getElementById('group-devices');
            groupDevices.innerHTML = '';
            devices.forEach(device => {
                const li = document.createElement('li');
                const deviceDiv = document.createElement('div');
                deviceDiv.className = 'device-entry';
                
                const status = device.active ? '🟢' : '💤';
                const deviceText = document.createElement('span');
                deviceText.textContent = `${status} ${device.name || device.id} (${device.ip})`;
                
                const removeBtn = document.createElement('button');
                removeBtn.textContent = 'Remove';
                removeBtn.className = 'remove-device-btn';
                removeBtn.onclick = () => removeFromGroup(device.device_id);
                
                deviceDiv.appendChild(deviceText);
                deviceDiv.appendChild(removeBtn);
                li.appendChild(deviceDiv);
                
                li.dataset.deviceId = device.device_id;
                li.draggable = true;
                li.addEventListener('dragstart', handleDragStart);
                // Add mouseover event for device info
                li.addEventListener('mouseover', () => showDeviceInfo(device));
                groupDevices.appendChild(li);
            });
        });
}

function removeFromGroup(deviceId) {
    fetch(`/devices/${deviceId}/group`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ group_id: null })
    }).then(response => {
        if (!response.ok) throw new Error('Failed to remove device from group');
        return response.json();
    }).then(() => {
        fetch('/devices')
            .then(response => response.json())
            .then(deviceData => {
                devices = deviceData;
                updateDeviceList(devices);
                // Refresh all group device lists
                document.querySelectorAll('#group-devices').forEach(groupList => {
                    const groupId = groupList.dataset.groupId;
                    if (groupId) {
                        fetchGroupDevices(groupId);
                    }
                });
            });
    });
}

// Create modal HTML
const modal = document.createElement('div');
modal.className = 'modal';
modal.innerHTML = `
    <div class="modal-content">
        <h3>Add New Group</h3>
        <input type="text" id="group-name-input" placeholder="Enter group name">
        <div class="modal-buttons">
            <button onclick="cancelAddGroup()">Cancel</button>
            <button onclick="confirmAddGroup()">Add</button>
        </div>
    </div>
`;
document.body.appendChild(modal);

// Update group creation handling
document.getElementById('add-group-tab').addEventListener('click', () => {
    modal.style.display = 'block';
});

function cancelAddGroup() {
    modal.style.display = 'none';
}

function confirmAddGroup() {
    const groupName = document.getElementById('group-name-input').value.trim();
    if (groupName) {
        fetch('/groups', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ name: groupName })
        }).then(response => response.json())
          .then(data => {
              addGroupTab(data.group_id, groupName);
              addGroupOption(data.group_id, groupName);
              modal.style.display = 'none';
          });
    }
}

function addGroupTab(groupId, groupName) {
    const tabList = document.getElementById('group-tab-list');
    const li = document.createElement('li');
    li.textContent = groupName;
    li.dataset.groupId = groupId;
    li.addEventListener('click', () => showGroupDetails(groupId));
    tabList.insertBefore(li, document.getElementById('add-group-tab'));
}

function addGroupOption(groupId, groupName) {
    const autoGroupSelect = document.getElementById('auto-group');
    const option = document.createElement('option');
    option.value = groupId;
    option.textContent = groupName;
    autoGroupSelect.appendChild(option);
}

function showGroupDetails(groupId) {
    fetch(`/groups/${groupId}`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(group => {
            const groupDetails = document.getElementById('group-details');
            groupDetails.innerHTML = `
                <h2>Group: <input type="text" value="${group.name}" data-group-id="${groupId}" class="group-name"></h2>
                <div class="group-album">
                    <label for="group-album">Album:</label>
                    <select id="group-album" data-group-id="${groupId}">
                        <option value="">Select an album</option>
                    </select>
                    <div class="group-album-info">
                        <p>Tracking status will appear here when an album is selected</p>
                    </div>
                </div>
                <label for="group-random">Random Order:</label>
                <input type="checkbox" id="group-random" ${group.random ? 'checked' : ''} data-group-id="${groupId}">
                <button id="delete-group" data-group-id="${groupId}">Delete Group</button>
                <div class="group-devices">
                    <h3>Devices in Group</h3>
                    <ul id="group-devices" class="droppable" data-group-id="${groupId}"></ul>
                </div>
            `;
            
            // Update active tab
            document.querySelectorAll('#group-tab-list li').forEach(tab => {
                tab.classList.remove('active');
                if (tab.dataset.groupId === groupId) {
                    tab.classList.add('active');
                }
            });

            // Set up event listeners
            const groupAlbumSelect = document.getElementById('group-album');
            document.querySelector('.group-name').addEventListener('input', handleGroupNameChange);
            groupAlbumSelect.addEventListener('change', handleGroupAlbumChange);
            document.getElementById('group-random').addEventListener('change', handleGroupRandomChange);
            document.getElementById('delete-group').addEventListener('click', handleGroupDelete);
            
            // Add droppable functionality
            const groupDevices = document.getElementById('group-devices');
            groupDevices.addEventListener('dragover', handleDragOver);
            groupDevices.addEventListener('drop', handleDrop);
            
            // Load albums and set selected
            fetch('/albums')
                .then(response => response.json())
                .then(albums => {
                    groupAlbumSelect.innerHTML = '<option value="">Select an album</option>';
                    albums.forEach(album => {
                        const option = document.createElement('option');
                        option.value = album.id;
                        option.textContent = album.albumName; // Use albumName instead of name
                        groupAlbumSelect.appendChild(option);
                    });
                    
                    if (group.album) {
                        groupAlbumSelect.value = group.album;
                        fetchAlbumTracking(groupId, group.album);
                        startTrackingAutoRefresh(groupId, group.album); // Start auto-refresh
                    }
                });
            
            fetchGroupDevices(groupId);
        })
        .catch(error => {
            console.error('Error fetching group details:', error);
        });
}

function fetchAlbumTracking(groupId, albumId) {
    fetch(`/groups/${groupId}/album-tracking/${albumId}`)
        .then(response => response.json())
        .then(tracking => {
            const infoDiv = document.querySelector('.group-album-info');
            infoDiv.innerHTML = `
                <p>Album Images: ${tracking.shown_count} / ${tracking.total_count}</p>
                <button onclick="resetTracking('${groupId}', '${albumId}')">Reset Tracking</button>
            `;
        });
}

// Add auto-refresh for album tracking
function startTrackingAutoRefresh(groupId, albumId) {
    // Clear any existing refresh interval
    if (window.trackingRefreshInterval) {
        clearInterval(window.trackingRefreshInterval);
    }
    
    // Set up new refresh interval if both IDs are present
    if (groupId && albumId) {
        window.trackingRefreshInterval = setInterval(() => {
            fetchAlbumTracking(groupId, albumId);
        }, 5000); // Refresh every 5 seconds
    }
}

function resetTracking(groupId, albumId) {
    fetch(`/groups/${groupId}/album-tracking/${albumId}/reset`, { method: 'POST' })
        .then(() => fetchAlbumTracking(groupId, albumId));
}

function handleDragStart(event) {
    const deviceId = event.target.dataset.deviceId;
    if (!deviceId) {
        console.error('No device ID found in dragged element');
        event.preventDefault();
        return;
    }
    console.log('Dragging device:', deviceId); // Debug log
    event.dataTransfer.setData('text/plain', deviceId);
}

document.querySelectorAll('.droppable').forEach(element => {
    element.addEventListener('dragover', handleDragOver);
    element.addEventListener('drop', handleDrop);
});

function handleDragOver(event) {
    event.preventDefault();
    event.currentTarget.classList.add('drag-over');
}

function handleDrop(event) {
    event.preventDefault();
    const deviceId = event.dataTransfer.getData('text/plain');
    const targetElement = event.currentTarget;
    const groupId = targetElement.dataset.groupId;
    
    if (!deviceId || deviceId === 'undefined') {
        console.error('Invalid device ID:', deviceId);
        return;
    }

    console.log('Dropping device:', deviceId, 'into group:', groupId); // Debug log

    if (groupId) {
        // Dropping into a group
        fetch(`/devices/${deviceId}/group`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ group_id: groupId })
        }).then(response => {
            if (!response.ok) throw new Error('Failed to assign device to group');
            return response.json();
        }).then(() => {
            fetchGroupDevices(groupId);
            fetch('/devices')
                .then(response => response.json())
                .then(deviceData => {
                    devices = deviceData;
                    updateDeviceList(devices);
                });
        }).catch(error => {
            console.error('Error assigning device to group:', error);
        });
    } else {
        // Dropping into discovered devices list (removing from group)
        fetch(`/devices/${deviceId}/group`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ group_id: null })
        }).then(response => {
            if (!response.ok) throw new Error('Failed to remove device from group');
            return response.json();
        }).then(() => {
            // Refresh both lists
            fetch('/devices')
                .then(response => response.json())
                .then(deviceData => {
                    devices = deviceData;
                    updateDeviceList(devices);
                    // Refresh all group device lists
                    document.querySelectorAll('#group-devices').forEach(groupList => {
                        const groupId = groupList.dataset.groupId;
                        if (groupId) {
                            fetchGroupDevices(groupId);
                        }
                    });
                });
        }).catch(error => {
            console.error('Error removing device from group:', error);
        });
    }
    event.currentTarget.classList.remove('drag-over');
}

function handleGroupNameChange(event) {
    const groupId = event.target.dataset.groupId;
    const newName = event.target.value;
    fetch(`/groups/${groupId}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name: newName })
    }).then(() => {
        // Update both the tab and dropdown option names
        const tab = document.querySelector(`#group-tab-list li[data-group-id="${groupId}"]`);
        const option = document.querySelector(`#auto-group option[value="${groupId}"]`);
        
        if (tab) {
            tab.textContent = newName;
        }
        if (option) {
            option.textContent = newName;
        }
    });
}

function handleGroupAlbumChange(event) {
    const groupId = event.target.dataset.groupId;
    const albumId = event.target.value;
    fetch(`/groups/${groupId}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ album: albumId })
    }).then(() => {
        if (albumId) {
            fetchAlbumTracking(groupId, albumId);
            startTrackingAutoRefresh(groupId, albumId);
        } else {
            // Clear refresh interval if no album selected
            if (window.trackingRefreshInterval) {
                clearInterval(window.trackingRefreshInterval);
            }
        }
    });
}

function handleGroupRandomChange(event) {
    const groupId = event.target.dataset.groupId;
    const isRandom = event.target.checked;
    fetch(`/groups/${groupId}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ random: isRandom })
    });
}

function handleGroupDelete(event) {
    const groupId = event.target.dataset.groupId;
    fetch(`/groups/${groupId}`, {
        method: 'DELETE'
    }).then(response => {
        if (!response.ok) throw new Error('Failed to delete group');
        return response.json();
    }).then(() => {
        // Remove the group tab and option
        document.querySelector(`#group-tab-list li[data-group-id="${groupId}"]`).remove();
        document.querySelector(`#auto-group option[value="${groupId}"]`).remove();
        document.getElementById('group-details').innerHTML = '';
        
        // No need to manually update devices list as the server will send a device_update event
    }).catch(error => {
        console.error('Error deleting group:', error);
    });
}

function showDeviceInfo(device) {
    const infoPopup = document.getElementById('device-info');
    const infoContent = document.getElementById('info-content');
    
    const firstSeen = new Date(device.first_seen).toLocaleString();
    const lastSeen = new Date(device.last_seen).toLocaleString();
    
    infoContent.innerHTML = `
        <p><strong>Name:</strong> ${device.name}</p>
        <p><strong>IP:</strong> ${device.ip}</p>
        <p><strong>Status:</strong> ${device.active ? 'Active' : 'Hibernating'}</p>
        <p><strong>First Seen:</strong> ${firstSeen}</p>
        <p><strong>Last Seen:</strong> ${lastSeen}</p>
        <p><strong>Width:</strong> ${device.width}</p>
        <p><strong>Height:</strong> ${device.height}</p>
        <p><strong>Dithering Palette Size:</strong> ${device.dithering_palette_size}</p>
        <p><strong>Buffer Size:</strong> ${device.buffer_size}</p>
        <p><strong>Free Space:</strong> ${device.free_space}</p>
    `;
    infoPopup.classList.add('active');
}

// Create info popup container if it doesn't exist
const infoPopup = document.createElement('div');
infoPopup.id = 'device-info';
infoPopup.innerHTML = '<div id="info-content"></div>';
document.body.appendChild(infoPopup);

// Add mouseleave event listener to hide device info
document.addEventListener('mouseleave', function(event) {
    const infoPopup = document.getElementById('device-info');
    infoPopup.classList.remove('active');
}, true);

// Replace the save button click handler with input change handlers
['wakeup-interval', 'rotation', 'enhanced', 'contrast'].forEach(setting => {
    document.getElementById(`${setting}-input`).addEventListener('change', (event) => {
        const value = parseFloat(event.target.value);
        const endpoint = setting === 'wakeup-interval' ? '/config/wakeup-interval' : '/config/immich';
        const payload = setting === 'wakeup-interval' 
            ? { wakeup_interval: value }
            : { [setting]: value };

        fetch(endpoint, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        }).catch(error => {
            console.error(`Error updating ${setting}:`, error);
            // Revert to previous value on error
            fetchImmichStatus();
        });
    });
});

function updateImmichStatus(status) {
    const serverSpan = document.querySelector('#immich-server span');
    const connectionSpan = document.querySelector('#immich-connection span');
    const albumsSpan = document.querySelector('#immich-albums span');
    
    serverSpan.textContent = status.server;
    connectionSpan.textContent = status.connected ? 'Connected' : 'Disconnected';
    connectionSpan.className = `connection-status ${status.connected ? 'connected' : 'disconnected'}`;
    albumsSpan.textContent = status.albums;

    // Update configuration inputs
    document.getElementById('wakeup-interval-input').value = status.wakeup_interval;
    document.getElementById('rotation-input').value = status.rotation;
    document.getElementById('enhanced-input').value = status.enhanced;
    document.getElementById('contrast-input').value = status.contrast;
}

function fetchImmichStatus() {
    fetch('/immich-status')
        .then(response => response.json())
        .then(status => {
            updateImmichStatus(status);
            document.getElementById('wakeup-interval-input').value = status.wakeup_interval;
        })
        .catch(error => {
            console.error('Error fetching Immich status:', error);
            updateImmichStatus({
                server: 'Unknown',
                connected: false,
                albums: 0,
                images: 0
            });
        });
}

// Poll Immich status every 30 seconds
fetchImmichStatus();
setInterval(fetchImmichStatus, 30000);

// Add function to load initial state
function loadInitialState() {
    // Clear existing groups
    document.querySelectorAll('#group-tab-list li:not(#add-group-tab)').forEach(el => el.remove());
    document.querySelectorAll('#auto-group option:not([value="none"])').forEach(el => el.remove());

    // Load devices
    fetch('/devices')
        .then(response => response.json())
        .then(deviceData => {
            console.log('Loading initial devices:', deviceData);
            updateDeviceList(deviceData);
        });

    // Load groups
    fetch('/groups')
        .then(response => response.json())
        .then(groupData => {
            console.log('Loading initial groups:', groupData);
            Object.entries(groupData).forEach(([groupId, group]) => {
                addGroupTab(groupId, group.name);
                addGroupOption(groupId, group.name);
            });
        });
}

// Call loadInitialState when page loads
document.addEventListener('DOMContentLoaded', function() {
    loadInitialState();
    fetchImmichStatus();
});

// Clean up refresh interval when switching groups or closing page
window.addEventListener('beforeunload', () => {
    if (window.trackingRefreshInterval) {
        clearInterval(window.trackingRefreshInterval);
    }
});