document.addEventListener("DOMContentLoaded", () => {
    const fileInput = document.getElementById("scale-file");
    const filenameSpan = document.getElementById("selected-filename");
    const knownDistanceInput = document.getElementById("known-distance");
    const btnCalibrate = document.getElementById("btn-calibrate");
    const canvas = document.getElementById("calibration-canvas");
    const ctx = canvas.getContext("2d");
    const placeholder = document.getElementById("canvas-placeholder");
    const canvasActions = document.getElementById("canvas-actions");
    const btnClearCanvas = document.getElementById("btn-clear-canvas");
    
    const ptA = document.getElementById("pt-a");
    const ptB = document.getElementById("pt-b");
    const ptDist = document.getElementById("pt-dist");
    
    const calibrationForm = document.getElementById("calibration-form");
    const calResultCard = document.getElementById("calibration-result");
    const factorDisplay = document.getElementById("factor-display");
    const historyTable = document.getElementById("cal-history-table");

    let imgElement = new Image();
    let points = []; // Array of {x, y} relative to natural image dimensions

    // 1. Load History on init
    loadCalibrationHistory();

    // 2. Handle File upload selection
    fileInput.addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        filenameSpan.innerText = file.name;
        
        const reader = new FileReader();
        reader.onload = (event) => {
            imgElement.src = event.target.result;
        };
        reader.readAsDataURL(file);
    });

    imgElement.onload = () => {
        // Clear previous state
        points = [];
        ptA.innerText = "—";
        ptB.innerText = "—";
        ptDist.innerText = "— px";
        btnCalibrate.disabled = true;
        
        // Hide placeholder, show canvas and actions
        placeholder.style.display = "none";
        canvas.style.display = "block";
        canvasActions.style.display = "flex";
        
        // Set canvas backing dimensions to match natural image size
        canvas.width = imgElement.naturalWidth;
        canvas.height = imgElement.naturalHeight;
        
        drawCanvas();
    };

    // 3. Draw image and points on canvas
    function drawCanvas() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        // Draw the scale image
        ctx.drawImage(imgElement, 0, 0);
        
        // Draw lines and dots if points are placed
        if (points.length > 0) {
            points.forEach((pt, index) => {
                ctx.beginPath();
                ctx.arc(pt.x, pt.y, 8, 0, 2 * Math.PI);
                ctx.fillStyle = index === 0 ? "#6366f1" : "#0ea5e9";
                ctx.shadowColor = index === 0 ? "rgba(99, 102, 241, 0.8)" : "rgba(14, 165, 233, 0.8)";
                ctx.shadowBlur = 12;
                ctx.fill();
                
                // Text label
                ctx.fillStyle = "white";
                ctx.font = "bold 16px Inter";
                ctx.shadowBlur = 0;
                ctx.fillText(`Pt ${index === 0 ? 'A' : 'B'}`, pt.x + 12, pt.y + 5);
            });
        }
        
        if (points.length === 2) {
            // Draw connecting line
            ctx.beginPath();
            ctx.moveTo(points[0].x, points[0].y);
            ctx.lineTo(points[1].x, points[1].y);
            ctx.lineWidth = 4;
            ctx.strokeStyle = "rgba(99, 102, 241, 0.8)";
            ctx.shadowColor = "rgba(99, 102, 241, 0.5)";
            ctx.shadowBlur = 10;
            ctx.stroke();
            ctx.shadowBlur = 0; // Reset
        }
    }

    // 4. Canvas Click Handlers
    canvas.addEventListener("click", (e) => {
        if (!imgElement.src) return;
        if (points.length >= 2) return; // Only allow 2 points
        
        const rect = canvas.getBoundingClientRect();
        
        // Convert screen coordinates to natural image coordinates
        const clickX = (e.clientX - rect.left) * (canvas.width / rect.width);
        const clickY = (e.clientY - rect.top) * (canvas.height / rect.height);
        
        points.push({ x: clickX, y: clickY });
        
        // Update stats
        if (points.length === 1) {
            ptA.innerText = `(${Math.round(points[0].x)}, ${Math.round(points[0].y)})`;
        } else if (points.length === 2) {
            ptB.innerText = `(${Math.round(points[1].x)}, ${Math.round(points[1].y)})`;
            
            // Calculate distance
            const dx = points[1].x - points[0].x;
            const dy = points[1].y - points[0].y;
            const distance = Math.sqrt(dx*dx + dy*dy);
            ptDist.innerText = `${Math.round(distance)} px`;
            
            // Enable calibration button
            btnCalibrate.disabled = false;
        }
        
        drawCanvas();
    });

    btnClearCanvas.addEventListener("click", () => {
        points = [];
        ptA.innerText = "—";
        ptB.innerText = "—";
        ptDist.innerText = "— px";
        btnCalibrate.disabled = true;
        drawCanvas();
    });

    // 5. Submit Calibration Form
    calibrationForm.addEventListener("submit", (e) => {
        e.preventDefault();
        
        if (points.length !== 2) {
            alert("Please select exactly two points on the image first.");
            return;
        }
        
        const knownDistance = parseFloat(knownDistanceInput.value);
        if (isNaN(knownDistance) || knownDistance <= 0) {
            alert("Please enter a valid known distance greater than zero.");
            return;
        }
        
        const file = fileInput.files[0];
        if (!file) {
            alert("Please select a scale image file.");
            return;
        }
        
        const formData = new FormData();
        formData.append("file", file);
        formData.append("known_distance", knownDistance);
        formData.append("x1", points[0].x);
        formData.append("y1", points[0].y);
        formData.append("x2", points[1].x);
        formData.append("y2", points[1].y);
        
        btnCalibrate.disabled = true;
        btnCalibrate.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Calibrating...`;
        
        fetch("/api/calibration/calibrate-scale", {
            method: "POST",
            body: formData
        })
        .then(res => {
            if (!res.ok) return res.json().then(d => { throw new Error(d.detail || "Error") });
            return res.json();
        })
        .then(data => {
            // Display Results
            calResultCard.style.display = "block";
            factorDisplay.innerHTML = `${data.pixels_per_mm.toFixed(2)} <span style="font-size:14px; font-weight:normal; color:var(--text-secondary)">px/mm</span>`;
            
            // Reload calibration history
            loadCalibrationHistory();
            
            // Reset button
            btnCalibrate.disabled = false;
            btnCalibrate.innerHTML = `<i class="fa-solid fa-calculator"></i> Recalibrate`;
        })
        .catch(err => {
            alert(`Calibration failed: ${err.message}`);
            btnCalibrate.disabled = false;
            btnCalibrate.innerHTML = `<i class="fa-solid fa-calculator"></i> Compute Calibration Factor`;
        });
    });

    // 6. History API Loader
    function loadCalibrationHistory() {
        fetch("/api/calibration/history")
            .then(res => res.json())
            .then(data => {
                if (data.length === 0) {
                    historyTable.innerHTML = `<tr><td colspan="3" class="text-center">No calibration factors saved yet</td></tr>`;
                    return;
                }
                
                historyTable.innerHTML = "";
                data.forEach(item => {
                    const date = new Date(item.created_at).toLocaleDateString();
                    historyTable.innerHTML += `
                        <tr style="cursor:pointer" onclick="selectFactor(${item.pixels_per_mm}, ${item.known_distance})">
                            <td>${date}</td>
                            <td><strong>${item.pixels_per_mm.toFixed(2)}</strong></td>
                            <td>${item.known_distance} mm</td>
                        </tr>
                    `;
                });
            })
            .catch(err => console.error("Error loading calibration history:", err));
    }
});

// Helper if user clicks a history row
function selectFactor(factor, distance) {
    const factorCard = document.getElementById("calibration-result");
    const factorDisplay = document.getElementById("factor-display");
    factorCard.style.display = "block";
    factorDisplay.innerHTML = `${factor.toFixed(2)} <span style="font-size:14px; font-weight:normal; color:var(--text-secondary)">px/mm</span>`;
}
