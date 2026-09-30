
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    // Shared camera elements
    const video = document.getElementById("video");
    const cameraHint = document.getElementById("cameraHint");
    const startCameraButton = document.getElementById("startCamera");
    const cameraStatus = document.getElementById("cameraStatus");

    // Registration elements
    const registerForm = document.getElementById("registerForm");
    const captureButton = document.getElementById("captureFace");
    const faceImageInput = document.getElementById("face_image");
    const captureNotice = document.getElementById("captureNotice");

    // Face verification elements
    const verifyButton = document.getElementById("verifyFace");
    const verificationStatus =
        document.getElementById("verificationStatus");
    const verifyTitle = document.getElementById("verifyTitle");
    const verifyMessage = document.getElementById("verifyMessage");
    const verifyIcon = document.getElementById("verifyIcon");

    let cameraStream = null;
    let cameraReady = false;

    function setCameraStatus(message) {
        if (cameraStatus) {
            cameraStatus.textContent = message;
        }
    }

    function showVerificationResult(type, title, message, icon) {
        if (!verificationStatus) return;

        verificationStatus.hidden = false;
        verificationStatus.className = `verify-result ${type}`;

        if (verifyTitle) verifyTitle.textContent = title;
        if (verifyMessage) verifyMessage.textContent = message;
        if (verifyIcon) verifyIcon.textContent = icon;
    }

    // Start or restart webcam
    async function startCamera() {
        if (!video) {
            setCameraStatus("Camera preview is unavailable on this page.");
            return;
        }

        if (!navigator.mediaDevices?.getUserMedia) {
            setCameraStatus(
                "Camera access is unavailable. Use localhost or HTTPS."
            );
            return;
        }

        if (startCameraButton) startCameraButton.disabled = true;

        try {
            stopCamera();

            setCameraStatus("Starting camera...");

            cameraStream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: "user",
                    width: { ideal: 640 },
                    height: { ideal: 480 }
                },
                audio: false
            });

            video.srcObject = cameraStream;
            await video.play();

            cameraReady = true;

            if (cameraHint) {
                cameraHint.hidden = true;
                cameraHint.style.display = "none";
            }

            if (startCameraButton) {
                startCameraButton.textContent = "Restart Camera";
            }

            if (verifyButton) verifyButton.disabled = false;

            setCameraStatus(
                "Camera is ready. Position your face in the frame."
            );
        } catch (error) {
            console.error("Camera startup error:", error);
            cameraReady = false;

            setCameraStatus(
                "Could not access camera. Allow camera permission and try again."
            );

            if (verificationStatus) {
                showVerificationResult(
                    "error",
                    "Camera access failed",
                    "Check your browser camera permission and try again.",
                    "📷"
                );
            }
        } finally {
            if (startCameraButton) {
                startCameraButton.disabled = false;
            }
        }
    }

    // Stop webcam and release the device
    function stopCamera() {
        if (cameraStream) {
            cameraStream.getTracks().forEach(track => track.stop());
            cameraStream = null;
        }

        if (video) {
            video.srcObject = null;
        }

        cameraReady = false;
    }

    // Capture one webcam image as a data URL
    function captureFaceImage() {
        if (!video || !cameraReady ||
            !video.videoWidth || !video.videoHeight) {
            throw new Error(
                "Please start the camera and wait for the preview."
            );
        }

        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;

        const context = canvas.getContext("2d");

        if (!context) {
            throw new Error("Unable to capture the camera image.");
        }

        context.drawImage(
            video,
            0,
            0,
            canvas.width,
            canvas.height
        );

        return canvas.toDataURL("image/jpeg", 0.9);
    }

    // Registration: capture the face into the hidden form field
    if (captureButton && faceImageInput) {
        captureButton.addEventListener("click", () => {
            try {
                faceImageInput.value = captureFaceImage();

                if (captureNotice) {
                    captureNotice.hidden = false;
                }

                captureButton.textContent = "Face Captured ✓";
                setCameraStatus(
                    "Face captured successfully. You can create your account."
                );
            } catch (error) {
                if (captureNotice) {
                    captureNotice.hidden = true;
                }

                setCameraStatus(error.message);
            }
        });
    }

    // Registration: require a captured face before submitting
    if (registerForm && faceImageInput) {
        registerForm.addEventListener("submit", event => {
            if (!faceImageInput.value) {
                event.preventDefault();
                setCameraStatus(
                    "Please start the camera and capture your face before registering."
                );

                if (captureButton) captureButton.focus();
            }
        });
    }

    // Login: send captured image to the Flask verification endpoint
    async function verifyFace() {
        if (!verifyButton) return;

        verifyButton.disabled = true;

        try {
            showVerificationResult(
                "pending",
                "Verifying your identity...",
                "Please keep your face visible and stay still.",
                "🔍"
            );

            setCameraStatus("Checking your face...");

            const image = captureFaceImage();

            const response = await fetch("/verify-face", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ image })
            });

            let result;

            try {
                result = await response.json();
            } catch {
                throw new Error("The server returned an invalid response.");
            }

            if (!response.ok) {
                throw new Error(
                    result.message || "Face verification request failed."
                );
            }

            if (result.ok === true) {
                showVerificationResult(
                    "success",
                    "Face matched successfully!",
                    "Your identity has been verified. Opening your dashboard...",
                    "✅"
                );

                setCameraStatus("Verification successful.");
                stopCamera();

                window.location.assign(
                    result.redirect || "/dashboard"
                );
            } else {
                showVerificationResult(
                    "error",
                    "Face did not match!",
                    result.message ||
                    "Please try again. Make sure your face is clearly visible and well-lit.",
                    "❌"
                );

                setCameraStatus(
                    "Face verification failed. You can try again."
                );
            }
        } catch (error) {
            console.error("Face verification error:", error);

            showVerificationResult(
                "error",
                "Verification failed!",
                error.message || "Please try again.",
                "⚠️"
            );

            setCameraStatus("Unable to complete verification.");
        } finally {
            verifyButton.disabled = false;
        }
    }

    if (verifyButton) {
        verifyButton.addEventListener("click", verifyFace);
        verifyButton.disabled = true;
    }

    // Attach camera startup to the page's button
    if (startCameraButton) {
        startCameraButton.addEventListener("click", startCamera);
    }

    // Release camera when leaving the page
    window.addEventListener("pagehide", stopCamera);
});