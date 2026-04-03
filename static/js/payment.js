/* ================================================================
   SECEL — Payment JS
   Handles: operator detection, payment initiation, status polling
   ================================================================ */

'use strict';

// ── State ────────────────────────────────────────────────────
let selectedProvider = 'auto';
let currentReference = null;
let pollTimer        = null;

// ── Operator Detection ───────────────────────────────────────
const ORANGE_PREFIXES = ['080', '082', '084', '085'];
const MTN_PREFIXES    = ['089', '090', '091', '097', '098'];

function normalizePhone(phone) {
  const digits = phone.replace(/\D/g, '');
  if (digits.startsWith('243') && digits.length === 12) return '0' + digits.slice(3);
  if (digits.startsWith('0') && digits.length === 10) return digits;
  if (digits.length === 9) return '0' + digits;
  return digits;
}

function detectOperatorFromPhone(phone) {
  const normalized = normalizePhone(phone);
  const prefix = normalized.substring(0, 3);
  if (ORANGE_PREFIXES.includes(prefix)) return 'orange_money';
  if (MTN_PREFIXES.includes(prefix))    return 'mtn_momo';
  return 'unknown';
}

function detectOperatorLive(value) {
  const hint = document.getElementById('operatorHint');
  if (!hint) return;

  const normalized = normalizePhone(value);
  if (normalized.length < 3) {
    hint.innerHTML = '<span>Entrez votre numéro pour détecter l\'opérateur</span>';
    hint.className = 'phone-hint';
    return;
  }

  const operator = detectOperatorFromPhone(normalized);
  if (operator === 'orange_money') {
    hint.innerHTML = '<i class="fas fa-check-circle me-1"></i><span class="hint-orange">Orange Money détecté</span>';
    hint.className = 'phone-hint hint-orange';
    if (selectedProvider === 'auto') updateProviderVisuals('orange_money');
  } else if (operator === 'mtn_momo') {
    hint.innerHTML = '<i class="fas fa-check-circle me-1"></i><span class="hint-mtn">MTN Mobile Money détecté</span>';
    hint.className = 'phone-hint hint-mtn';
    if (selectedProvider === 'auto') updateProviderVisuals('mtn_momo');
  } else {
    hint.innerHTML = '<i class="fas fa-exclamation-circle me-1"></i><span class="hint-unknown">Opérateur non reconnu (vérifiez le préfixe)</span>';
    hint.className = 'phone-hint hint-unknown';
    if (selectedProvider === 'auto') updateProviderVisuals(null);
  }
}

function updateProviderVisuals(provider) {
  const infoOrange = document.getElementById('infoOrange');
  const infoMtn    = document.getElementById('infoMtn');
  if (infoOrange) infoOrange.style.display = (provider === 'orange_money') ? 'flex' : 'none';
  if (infoMtn)    infoMtn.style.display    = (provider === 'mtn_momo')    ? 'flex' : 'none';
}

function selectProvider(provider, btn) {
  selectedProvider = provider;

  // Update button states
  document.querySelectorAll('.prov-tab').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');

  // Show/hide info boxes
  updateProviderVisuals(provider === 'auto' ? null : provider);

  // Update hidden field
  const hp = document.getElementById('hiddenProvider');
  if (hp) hp.value = provider;
}

// ── Payment Initiation ───────────────────────────────────────
function initiatePayment(e) {
  e.preventDefault();

  const phone   = document.getElementById('phoneInput').value.trim();
  const payBtn  = document.getElementById('payBtn');

  if (!phone) {
    showToast('Veuillez entrer votre numéro de téléphone', 'warning');
    return;
  }

  // Normalize phone
  const normalizedPhone = normalizePhone(phone);
  if (normalizedPhone.length < 9) {
    showToast('Numéro de téléphone invalide', 'error');
    return;
  }

  // Determine provider
  let provider = selectedProvider;
  if (provider === 'auto') {
    provider = detectOperatorFromPhone(normalizedPhone);
    if (provider === 'unknown') {
      showToast('Opérateur non reconnu. Choisissez Orange Money ou MTN MoMo manuellement.', 'error');
      return;
    }
  }

  // Disable button, show loading
  payBtn.disabled = true;
  payBtn.innerHTML = '<div class="spinner-border spinner-border-sm me-2" role="status"></div>Traitement en cours…';

  fetch('/api/payment/initiate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      course_id: (typeof CHECKOUT_COURSE_ID !== 'undefined') ? CHECKOUT_COURSE_ID : null,
      phone:     normalizedPhone,
      amount:    (typeof CHECKOUT_AMOUNT   !== 'undefined') ? CHECKOUT_AMOUNT   : 0,
      currency:  (typeof CHECKOUT_CURRENCY !== 'undefined') ? CHECKOUT_CURRENCY : 'USD',
      provider:  provider,
    })
  })
  .then(r => r.json())
  .then(data => {
    if (data.status === 'error') {
      throw new Error(data.message || 'Erreur lors de l\'initiation du paiement');
    }
    showInstructions(data);
  })
  .catch(err => {
    payBtn.disabled = false;
    payBtn.innerHTML = `<i class="fas fa-lock me-2"></i>Payer maintenant`;
    showToast(err.message, 'error');
  });
}

// ── Show Instructions ─────────────────────────────────────────
function showInstructions(data) {
  currentReference = data.reference;

  // Hide form, show instructions panel
  document.getElementById('checkoutForm').style.display = 'none';
  const instrPanel = document.getElementById('paymentInstructions');
  instrPanel.style.display = 'block';

  // Populate content
  document.getElementById('piText').textContent  = data.instructions || '';
  document.getElementById('piRef').textContent   = data.reference || '';

  const ussdEl = document.getElementById('piUssd');
  if (data.ussd_string) {
    ussdEl.style.display = 'block';
    ussdEl.textContent = data.ussd_string;
  } else {
    ussdEl.style.display = 'none';
  }

  // Start polling
  startPolling(data.reference);
}

// ── Status Polling ─────────────────────────────────────────────
function startPolling(reference) {
  let attempts = 0;
  const maxAttempts = 24; // ~2 minutes (every 5 seconds)

  pollTimer = setInterval(() => {
    attempts++;
    if (attempts > maxAttempts) {
      clearInterval(pollTimer);
      showPaymentFailed('Délai dépassé. Veuillez vérifier votre téléphone.');
      return;
    }

    fetch(`/api/payment/status/${reference}`)
      .then(r => r.json())
      .then(data => {
        if (data.status === 'success') {
          clearInterval(pollTimer);
          showPaymentSuccess();
        } else if (data.status === 'failed' || data.status === 'cancelled') {
          clearInterval(pollTimer);
          showPaymentFailed();
        }
        // 'pending' → continue polling
      })
      .catch(() => {}); // silently retry on network errors
  }, 5000);
}

// ── Demo: Simulate confirmation ────────────────────────────────
function demoConfirm() {
  if (!currentReference) return;
  const btn = document.getElementById('demoConfirmBtn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<div class="spinner-border spinner-border-sm me-2" role="status"></div>Simulation…'; }

  fetch(`/api/payment/confirm/${currentReference}`, { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      clearInterval(pollTimer);
      if (data.status === 'success') {
        showPaymentSuccess();
      } else {
        showPaymentFailed();
      }
    })
    .catch(() => showPaymentFailed());
}

// ── UI State Transitions ──────────────────────────────────────
function showPaymentSuccess() {
  document.getElementById('paymentInstructions').style.display = 'none';
  document.getElementById('paymentSuccess').style.display = 'block';
}

function showPaymentFailed(msg) {
  document.getElementById('paymentInstructions').style.display = 'none';
  document.getElementById('paymentFailed').style.display = 'block';
}

function resetCheckout() {
  clearInterval(pollTimer);
  currentReference = null;
  const payBtn = document.getElementById('payBtn');
  if (payBtn) {
    payBtn.disabled = false;
    payBtn.innerHTML = `<i class="fas fa-lock me-2"></i>Payer maintenant`;
  }
  document.getElementById('checkoutForm').style.display = 'block';
  document.getElementById('paymentFailed').style.display = 'none';
  document.getElementById('paymentSuccess').style.display = 'none';
  document.getElementById('paymentInstructions').style.display = 'none';
}

// ── Toast Notifications ───────────────────────────────────────
function showToast(message, type) {
  type = type || 'info';
  const colors = {
    success: '#3fb950', error: '#f85149', warning: '#f0a500', info: '#58a6ff'
  };
  const icons = {
    success: 'fa-check-circle', error: 'fa-times-circle', warning: 'fa-exclamation-triangle', info: 'fa-info-circle'
  };
  const toast = document.createElement('div');
  toast.style.cssText = `
    position: fixed; bottom: 24px; right: 24px; z-index: 9999;
    background: #161b22; border: 1px solid ${colors[type]};
    border-radius: 10px; padding: 12px 20px;
    display: flex; align-items: center; gap: 10px;
    color: ${colors[type]}; font-size: .875rem; font-weight: 600;
    box-shadow: 0 8px 24px rgba(0,0,0,.4);
    animation: slideInToast .3s ease;
    max-width: 360px;
  `;
  toast.innerHTML = `<i class="fas ${icons[type]}"></i> ${message}`;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity .3s';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ── CSS animation for toast ──────────────────────────────────
const style = document.createElement('style');
style.textContent = `
  @keyframes slideInToast {
    from { transform: translateX(100px); opacity: 0; }
    to   { transform: translateX(0);     opacity: 1; }
  }
`;
document.head.appendChild(style);
