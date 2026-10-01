import { initializeApp } from "https://www.gstatic.com/firebasejs/12.19.0/firebase-app.js";
import {
  getAuth,
  initializeRecaptchaConfig,
  RecaptchaVerifier,
  signInWithPhoneNumber,
  signOut,
} from "https://www.gstatic.com/firebasejs/12.19.0/firebase-auth.js";

const root = document.getElementById("firebase-phone-auth");
if (root) {
  const configElement = document.getElementById("firebase-phone-config");
  const config = configElement ? JSON.parse(configElement.textContent) : null;
  const phoneNumber = root.dataset.phoneNumber;
  const authorizeUrl = root.dataset.authorizeUrl;
  const sentUrl = root.dataset.sentUrl;
  const failureUrl = root.dataset.failureUrl;
  const sendButton = document.getElementById("send-sms-code");
  const resendButton = document.getElementById("resend-sms-code");
  const status = document.getElementById("firebase-phone-status");
  const recaptchaContainer = document.getElementById("firebase-recaptcha-container");
  const captchaComplete = document.getElementById("firebase-captcha-complete");
  const verifyForm = document.getElementById("firebase-sms-verify-form");
  const codeField = document.getElementById("sms-code-field");
  const codeInput = document.getElementById("id_code");
  const tokenInput = document.getElementById("firebase-id-token");
  const verifyButton = document.getElementById("verify-sms-code");

  let auth;
  let recaptchaVerifier;
  let confirmationResult;
  let sending = false;
  let captchaVerified = false;
  let captchaVisible = false;

  function setStatus(message, isError = false) {
    status.textContent = message;
    status.dataset.state = isError ? "error" : "info";
  }

  async function postJson(url) {
    const csrfToken = verifyForm.querySelector("[name=csrfmiddlewaretoken]").value;
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken, Accept: "application/json" },
    });
    const body = await response.json();
    if (!response.ok) {
      const error = new Error(body.error || "The request could not be completed.");
      error.status = response.status;
      error.nextAvailableAt = body.nextAvailableAt;
      throw error;
    }
    return body;
  }

  function canSendNow() {
    const cooldownUntil = Number(
      document.querySelector("[data-otp-countdown]")?.dataset.resendAt
      || document.querySelector("[data-otp-resend-countdown]")?.dataset.resendAt
      || 0
    );
    return cooldownUntil <= Date.now() / 1000;
  }

  function updateSendState() {
    const enabled = captchaVerified && !sending && canSendNow();
    sendButton.disabled = !enabled;
    resendButton.disabled = resendButton.hidden ? !canSendNow() : (sending || !canSendNow());
    sendButton.dataset.captchaVerified = captchaVerified ? "true" : "false";
  }

  async function resetRecaptcha() {
    captchaVerified = false;
    captchaVisible = false;
    sendButton.dataset.captchaVerified = "false";
    if (recaptchaVerifier) {
      await recaptchaVerifier.clear();
      recaptchaVerifier = null;
    }
    recaptchaContainer.replaceChildren();
    recaptchaContainer.hidden = false;
    captchaComplete.hidden = true;
    recaptchaVerifier = new RecaptchaVerifier(auth, recaptchaContainer, {
      size: "normal",
      callback: () => {
        captchaVerified = true;
        updateSendState();
        setStatus("Security check complete. You can request the SMS code.");
      },
      "expired-callback": () => {
        captchaVerified = false;
        updateSendState();
        setStatus("The security check expired. Complete it again before requesting a code.", true);
      },
    });
    await recaptchaVerifier.render();
    captchaVisible = true;
    updateSendState();
  }

  async function prepareFirebase() {
    const app = initializeApp(config);
    if (config.appCheckSiteKey) {
      const { initializeAppCheck, ReCaptchaEnterpriseProvider } = await import(
        "https://www.gstatic.com/firebasejs/12.19.0/firebase-app-check.js"
      );
      initializeAppCheck(app, {
        provider: new ReCaptchaEnterpriseProvider(config.appCheckSiteKey),
        isTokenAutoRefreshEnabled: true,
      });
    }
    auth = getAuth(app);
    auth.languageCode = "en";
    await initializeRecaptchaConfig(auth);
    await resetRecaptcha();
  }

  function explainFirebaseError(error) {
    const knownMessages = {
      "auth/invalid-phone-number": "This account’s phone number is not in a valid international format. Ask an administrator to update it.",
      "auth/missing-phone-number": "This account does not have a phone number for SMS verification. Ask an administrator to update it.",
      "auth/invalid-verification-code": "That code is incorrect. Check the text and try again.",
      "auth/code-expired": "That code expired. Request a new SMS code.",
      "auth/too-many-requests": "Firebase has temporarily limited requests for this number. Wait before trying again.",
      "auth/captcha-check-failed": "The security check did not complete. Try again.",
      "auth/invalid-app-credential": "Firebase could not validate the security check. Confirm this portal’s domain is authorized in Firebase Authentication, then try again.",
      "auth/unauthorized-domain": "This portal domain is not authorized in Firebase Authentication. Add it under Authentication settings → Authorized domains.",
      "auth/app-not-authorized": "Firebase does not authorize this portal to use phone sign-in. Check the Firebase web app and API key configuration.",
      "auth/invalid-api-key": "The Firebase API key is invalid. Check the web app configuration in Firebase.",
      "auth/operation-not-allowed": "Phone sign-in is not enabled for this Firebase project.",
      "auth/billing-not-enabled": "Firebase SMS sending requires the project to be linked to a Cloud Billing account.",
      "auth/region-not-allowed": "Firebase’s SMS region policy does not allow messages to this country.",
      "auth/quota-exceeded": "Firebase’s SMS quota has been reached. Try later or check the project’s billing and SMS limits.",
      "auth/error-code:-39": "Firebase’s SMS service returned internal error 39. The request did not confirm that a code was sent. Wait before trying again; if this keeps happening, contact Firebase Support with this error.",
      "auth/network-request-failed": "The browser could not reach Firebase. Check the internet connection and try again.",
    };
    const code = typeof error?.code === "string" ? error.code : "";
    return knownMessages[code] || `Firebase could not send or verify the text message${code ? ` (${code})` : ""}. Please try again later.`;
  }

  async function requestSms() {
    if (sending) return;
    if (!captchaVerified) {
      setStatus("Complete the security check before requesting an SMS code.", true);
      return;
    }
    sending = true;
    updateSendState();
    setStatus("Checking the request and sending your SMS code…");
    try {
      const authorization = await postJson(authorizeUrl);
      if (authorization.nextAvailableAt) {
        window.authShieldOtpCountdown?.updateResendAt(authorization.nextAvailableAt);
      }
      confirmationResult = await signInWithPhoneNumber(auth, phoneNumber, recaptchaVerifier);
      const sent = await postJson(sentUrl);
      window.authShieldOtpCountdown?.update(sent.expiresAt, sent.resendAvailableAt);
      codeField.hidden = false;
      codeInput.disabled = false;
      codeInput.value = "";
      verifyButton.disabled = true;
      sendButton.hidden = true;
      resendButton.hidden = false;
      captchaVerified = false;
      captchaVisible = false;
      sendButton.dataset.captchaVerified = "false";
      recaptchaContainer.hidden = true;
      captchaComplete.hidden = false;
      codeInput.focus();
      setStatus("SMS requested. Your security check was completed; enter the six-digit code from the text message.");
    } catch (error) {
      if (error.nextAvailableAt) {
        window.authShieldOtpCountdown?.updateResendAt(error.nextAvailableAt);
      }
      setStatus(error.status ? error.message : explainFirebaseError(error), true);
      if (recaptchaVerifier) {
        try {
          await resetRecaptcha();
        } catch {
          captchaVerified = false;
          updateSendState();
        }
      }
    } finally {
      sending = false;
      updateSendState();
    }
  }

  if (!config?.apiKey || !config?.projectId || !phoneNumber) {
    sendButton.disabled = true;
    setStatus("SMS sign-in is not configured for this portal. Choose Email or contact the administrator.", true);
  } else {
    sendButton.disabled = true;
    sendButton.dataset.captchaVerified = "false";
    setStatus("Preparing the security check…");
    prepareFirebase().then(() => {
      if (!captchaVerified) setStatus("Complete the security check before requesting an SMS code.");
      updateSendState();
    }).catch(() => {
      sendButton.disabled = true;
      setStatus("The security check could not load. Refresh the page and try again.", true);
    });

    sendButton.addEventListener("click", requestSms);
    resendButton.addEventListener("click", async () => {
      if (sending) return;
      if (!captchaVerified) {
        sendButton.disabled = true;
        resendButton.disabled = true;
        setStatus("Complete the security check to request a replacement SMS code.");
        if (!captchaVisible) {
          try {
            await resetRecaptcha();
          } catch {
            setStatus("The security check could not load. Refresh the page and try again.", true);
          }
        }
        return;
      }
      await requestSms();
    });
    codeInput.addEventListener("input", () => {
      codeInput.value = codeInput.value.replace(/\D/g, "").slice(0, 6);
      verifyButton.disabled = !confirmationResult || codeInput.value.length !== 6;
    });
    verifyForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!confirmationResult || codeInput.value.length !== 6) return;
      verifyButton.disabled = true;
      verifyButton.textContent = "Verifying…";
      setStatus("Checking your code…");
      try {
        const result = await confirmationResult.confirm(codeInput.value);
        tokenInput.value = await result.user.getIdToken(true);
        await signOut(auth);
        verifyForm.submit();
      } catch (error) {
        verifyButton.disabled = false;
        verifyButton.textContent = "Verify and sign in";
        if (["auth/invalid-verification-code", "auth/code-expired"].includes(error?.code)) {
          try {
            await postJson(failureUrl);
          } catch (failureError) {
            setStatus(failureError.message, true);
            if (failureError.status === 429 || failureError.status === 400) window.location.reload();
            return;
          }
        }
        setStatus(explainFirebaseError(error), true);
        if (error?.code === "auth/code-expired") {
          codeInput.value = "";
          verifyButton.disabled = true;
        }
      }
    });
  }
}
