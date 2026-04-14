(() => {
    "use strict";

    const API_ENDPOINTS = {
        devices: "/api/devices",
        block: "/api/block",
        unblock: "/api/unblock",
    };

    const dom = {
        deviceList: null,
        refreshButton: null,
        targetNodeSelect: null // Thêm biến hứng Dropdown chọn IP
    };

    let trafficChart;
    const maxDataPoints = 30; // Hiển thị 30 giây gần nhất
    let labels = [];
    let rxData = []; // Download
    let txData = []; // Upload

    document.addEventListener("DOMContentLoaded", initializeDashboard);

    function initializeDashboard() {
        dom.deviceList = document.getElementById("device-list");
        dom.refreshButton = document.getElementById("refresh-devices-btn");
        dom.targetNodeSelect = document.getElementById("targetNodeSelect"); // Mapping HTML

        if (!dom.deviceList) {
            console.error("Missing #device-list element");
            return;
        }

        if (dom.refreshButton) {
            dom.refreshButton.addEventListener("click", loadDevices);
        }

        dom.deviceList.addEventListener("click", onDeviceActionClick);

        const btnApplyCustomRule = document.getElementById("btnApplyCustomRule");
        if (btnApplyCustomRule) {
            btnApplyCustomRule.addEventListener("click", sendCustomRule);
        }

        // Bắt sự kiện khi người dùng đổi IP theo dõi
        if (dom.targetNodeSelect) {
            dom.targetNodeSelect.addEventListener("change", () => {
                // Xóa sạch biểu đồ cũ khi chuyển sang Node khác
                labels.length = 0;
                rxData.length = 0;
                txData.length = 0;
                if (trafficChart) trafficChart.update();
            });
        }

        // Khởi tạo các thành phần
        loadDevices();
        initChart();
        setInterval(updateChart, 1000); // Lặp vẽ biểu đồ mỗi 1s
    }

    // --- CÁC HÀM QUẢN LÝ THIẾT BỊ ---

    function onDeviceActionClick(event) {
        const button = event.target.closest("button[data-action][data-mac]");
        if (!button) return;

        const mac = button.getAttribute("data-mac");
        const action = button.getAttribute("data-action");

        if (!mac || !action) return;

        toggleBlock(mac, action);
    }

    function setLoadingState() {
        dom.deviceList.innerHTML = `
            <tr>
                <td colspan="6" class="text-center py-4">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <p class="mt-2 text-muted">Refreshing data...</p>
                </td>
            </tr>
        `;
    }

    function setMessageState(message, isError = false) {
        const messageClass = isError ? "text-danger" : "text-muted";
        dom.deviceList.innerHTML = `
            <tr>
                <td colspan="6" class="text-center py-4 ${messageClass}">${escapeHtml(message)}</td>
            </tr>
        `;
    }

    async function loadDevices() {
        setLoadingState();

        try {
            const response = await fetch(API_ENDPOINTS.devices);

            if (!response.ok) {
                throw new Error(`Request failed with status ${response.status}`);
            }

            const payload = await response.json();

            if (payload.status !== "success") {
                setMessageState(`Server error: ${payload.message || "Unknown error"}`, true);
                return;
            }

            const devices = Array.isArray(payload.data) ? payload.data : [];
            renderDeviceRows(devices);
            updateTargetDropdown(devices); // Đổ IP vào ô chọn biểu đồ

        } catch (error) {
            console.error("Failed to load devices:", error);
            setMessageState("Lost connection to API server!", true);
        }
    }

    function renderDeviceRows(devices) {
        if (!devices.length) {
            setMessageState("No devices found on the network.");
            return;
        }

        const rows = devices.map((device) => createDeviceRowMarkup(device)).join("");
        dom.deviceList.innerHTML = rows;
    }

    function createDeviceRowMarkup(device) {
        const isBlocked = Number(device.IsBlocked) === 1;

        const displayName = escapeHtml(device.CustomName || device.OriginalName || "Unknown");
        const ipAddress = escapeHtml(device.IpAddress || "-");
        const macAddress = escapeHtml(device.MacAddress || "-");
        const lastSeen = escapeHtml(device.LastSeen || "-");

        const statusBadge = createStatusBadgeMarkup(isBlocked, Boolean(device.IsOnline));
        const actionButton = createActionButtonMarkup(isBlocked, device.MacAddress || "");

        return `
            <tr>
                <td class="fw-bold align-middle">${displayName}</td>
                <td class="align-middle">${ipAddress}</td>
                <td class="mac-font align-middle">${macAddress}</td>
                <td class="align-middle">${statusBadge}</td>
                <td class="align-middle text-muted">${lastSeen}</td>
                <td class="text-center align-middle">${actionButton}</td>
            </tr>
        `;
    }

    function createStatusBadgeMarkup(isBlocked, isOnline) {
        if (isBlocked) {
            return '<span class="badge bg-danger"><i class="fas fa-lock me-1"></i>Blocked</span>';
        }
        if (isOnline) {
            return '<span class="badge bg-success"><i class="fas fa-globe me-1"></i>Online</span>';
        }
        return '<span class="badge bg-secondary"><i class="fas fa-moon me-1"></i>Offline</span>';
    }

    function createActionButtonMarkup(isBlocked, macAddress) {
        const action = isBlocked ? "unblock" : "block";
        const icon = isBlocked ? "fa-unlock" : "fa-ban";
        const text = isBlocked ? "Unblock" : "Block MAC";
        const buttonClass = isBlocked ? "btn-outline-success" : "btn-outline-danger";

        return `
            <button type="button" class="btn btn-sm ${buttonClass}" data-action="${action}" data-mac="${escapeHtml(macAddress)}">
                <i class="fas ${icon} me-1"></i>${text}
            </button>
        `;
    }

    // Hàm mới: Đổ IP thiết bị vào Dropdown
    function updateTargetDropdown(devices) {
        if (!dom.targetNodeSelect) return;
        const currentSelection = dom.targetNodeSelect.value;
        let optionsHtml = '<option value="">-- Chọn một thiết bị để soi --</option>';

        devices.forEach(dev => {
            if (dev.IpAddress) {
                const name = dev.CustomName || dev.OriginalName || "Unknown";
                optionsHtml += `<option value="${dev.IpAddress}">${name} (${dev.IpAddress})</option>`;
            }
        });

        dom.targetNodeSelect.innerHTML = optionsHtml;

        // Cố gắng giữ lại thiết bị đang soi nếu nó vẫn tồn tại
        if (currentSelection && Array.from(dom.targetNodeSelect.options).some(opt => opt.value === currentSelection)) {
            dom.targetNodeSelect.value = currentSelection;
            return;
        }

        // Tự động chọn thiết bị đầu tiên để biểu đồ bắt đầu chạy ngay.
        const firstValidOption = Array.from(dom.targetNodeSelect.options).find(opt => opt.value);
        if (firstValidOption) {
            dom.targetNodeSelect.value = firstValidOption.value;
        }
    }

    // --- CÁC HÀM API KHÁC ---

    async function toggleBlock(mac, action) {
        const endpoint = action === "block" ? API_ENDPOINTS.block : API_ENDPOINTS.unblock;
        try {
            const response = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mac }),
            });

            if (!response.ok) throw new Error(`Request failed with status ${response.status}`);
            const payload = await response.json();

            if (payload.status !== "success") {
                alert(`Error: ${payload.message || "Unknown error"}`);
                return;
            }

            await loadDevices();
        } catch (error) {
            console.error("Failed to update firewall rule:", error);
            alert("Cannot connect to the iptables command server!");
        }
    }

    async function sendCustomRule() {
        const payload = {
            action: document.getElementById("ruleAction").value,
            chain: "FORWARD",
            protocol: document.getElementById("ruleProtocol").value,
            target: document.getElementById("ruleTarget").value,
            src_ip: document.getElementById("ruleSrcIp").value.trim() || null,
            dst_ip: document.getElementById("ruleDstIp").value.trim() || null,
            sport: document.getElementById("ruleSport").value.trim() || null,
            dport: document.getElementById("ruleDport").value.trim() || null
        };

        try {
            const response = await fetch("/api/custom_rule", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            
            const result = await response.json();
            
            if (result.status === "success") {
                alert(result.message);
                const modalEl = document.getElementById("customRuleModal");
                const modalInstance = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
                modalInstance.hide();
            } else {
                alert("Error: " + result.message);
            }
        } catch (error) {
            console.error("Error while sending custom rule:", error);
            alert("Cannot connect to server!");
        }
    }

    // --- CHART & DASHBOARD LOGIC ---

    function initChart() {
        const ctx = document.getElementById('trafficChart').getContext('2d');
        trafficChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Client Upload (RX KB/s)',
                        data: rxData,
                        borderColor: '#e74c3c', // Màu đỏ cảnh báo
                        backgroundColor: 'rgba(231, 76, 60, 0.2)',
                        fill: true,
                        tension: 0.4
                    },
                    {
                        label: 'Client Download (TX KB/s)', // Đã đổi nhãn cho dễ hiểu
                        data: txData,
                        borderColor: '#2ecc71', // Màu xanh an toàn
                        backgroundColor: 'rgba(46, 204, 113, 0.2)',
                        fill: true,
                        tension: 0.4
                    }
                ]
            },
            options: { 
                responsive: true,
                animation: false, 
                scales: { y: { beginAtZero: true } }
            }
        });
    }

    async function updateChart() {
        if (!dom.targetNodeSelect) return;
        const selectedIp = dom.targetNodeSelect.value;

        // NẾU CHƯA CHỌN IP NÀO, KHÔNG LÀM GÌ CẢ
        if (!selectedIp) return;

        try {
            // Nối IP vào đường dẫn để gọi API đo cục bộ
            const encodedIp = encodeURIComponent(selectedIp);
            const res = await fetch(`/api/stats?ip=${encodedIp}`);
            const json = await res.json();
            
            if (json.status === 'success') {
                if (labels.length >= maxDataPoints) { // Đã sửa lỗi off-by-one
                    labels.shift();
                    rxData.shift();
                    txData.shift();
                }
                
                labels.push(json.timestamp);
                // Bắt đúng tên biến từ API Backend mới
                rxData.push(json.client_upload_kbps);
                txData.push(json.client_download_kbps);
                
                trafficChart.update();
            }
        } catch (error) {
            console.error("Lỗi lấy dữ liệu mạng", error);
        }
    }

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }
})();