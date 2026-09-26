import { initializeApp } from "https://www.gstatic.com/firebasejs/12.19.0/firebase-app.js";
import {
  getAuth,
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
  const verifyForm = document.getElementById("firebase-sms-verify-form");
  const codeField = document.getElementById("sms-code-field");
  const codeInput = document.getElementById("id_code");
  const tokenInput = document.getElementById("firebase-id-token");
  const verifyButton = document.getElementById("verify-sms-code");

  let auth;
  let recaptchaVerifier;
  let confirmationResult;
  let sending = false;

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
      throw error;
    }
    return body;
  }

  async function resetRecaptcha() {
    if (recaptchaVerifier) {
      await recaptchaVerifier.clear();
      recaptchaVerifier = null;
    }
    recaptchaContainer.replaceChildren();
    recaptchaVerifier = new RecaptchaVerifier(auth, recaptchaContainer, { size: "normal" });
    await recaptchaVerifier.render();
  }

  function explainFirebaseError(error) {
    const knownMessages = {
      "auth/invalid-phone-number": "This account’s phone number is not in a valid international format. Ask an administrator to update it.",
      "auth/invalid-verification-code": "That code is incorrect. Check the text and try again.",
      "auth/code-expired": "That code expired. Request a new SMS code.",
      "auth/too-many-requests": "Firebase has temporarily limited requests for this number. Wait before trying again.",
      "auth/captcha-check-failed": "The security check did not complete. Try again.",
      "auth/quota-exceeded": "Firebase’s SMS quota has been reached. Try later or check the project’s billing and SMS limits.",
    };
    return knownMessages[error?.code] || "Firebase could not send or verify the text message. Please try again later.";
  }

  async function requestSms() {
    if (sending) return;
    sending = true;
    sendButton.disabled = true;
    resendButton.disabled = true;
    setStatus("Checking the request and preparing the security check…");
    try {
      await postJson(authorizeUrl);
      if (!auth) {
        const app = initializeApp(config);
        auth = getAuth(app);
        auth.languageCode = "en";
      }
      await resetRecaptcha();
      confirmationResult = await signInWithPhoneNumber(auth, phoneNumber, recaptchaVerifier);
      await postJson(sentUrl);
      codeField.hidden = false;
      codeInput.disabled = false;
      codeInput.value = "";
      verifyButton.disabled = true;
      sendButton.hidden = true;
      resendButton.hidden = false;
      codeInput.focus();
      setStatus("The SMS request was accepted. Enter the six-digit code from the text message.");
    } catch (error) {
      setStatus(error.status ? error.message : explainFirebaseError(error), true);
      if (recaptchaVerifier && error?.code?.startsWith("auth/")) {
        await recaptchaVerifier.clear().catch(() => {});
        recaptchaVerifier = null;
        recaptchaContainer.replaceChildren();
      }
    } finally {
      sending = false;
      sendButton.disabled = false;
      resendButton.disabled = false;
    }
  }

  if (!config?.apiKey || !config?.projectId || !phoneNumber) {
    sendButton.disabled = true;
    setStatus("SMS sign-in is not configured for this portal. Choose Email or contact the administrator.", true);
  } else {
    sendButton.addEventListener("click", requestSms);
    resendButton.addEventListener("click", requestSms);
    codeInput.addEventListener("input", () => {
      codeInput.value = codeInput.value.replace(/\D/g, "").slice(0, 6);
      verifyButton.disabled = codeInput.value.length !== 6;
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
