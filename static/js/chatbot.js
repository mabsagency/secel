// ═══════════════════════════════════════════════════════
// SECEL SELA Chatbot — Multilingual (FR / EN / ZH)
// ═══════════════════════════════════════════════════════

(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────
  let isOpen = false;
  let currentLang = 'fr';
  let messageCount = 0;
  let isTyping = false;

  // Historique de conversation (mémoire de SELA)
  // Format : [{role: 'user'|'assistant', content: '...'}]
  let conversationHistory = [];
  const MAX_HISTORY = 20; // 10 échanges conservés en mémoire

  // ── DOM Refs ───────────────────────────────────────────
  const toggle     = document.getElementById('chatbotToggle');
  const panel      = document.getElementById('chatbotPanel');
  const closeBtn   = document.getElementById('chatbotClose');
  const messagesEl = document.getElementById('chatbotMessages');
  const inputEl    = document.getElementById('chatbotInput');
  const sendBtn    = document.getElementById('chatbotSend');
  const badge      = document.getElementById('chatbotBadge');
  const iconOpen   = toggle?.querySelector('.chatbot-icon-open');
  const iconClose  = toggle?.querySelector('.chatbot-icon-close');

  if (!toggle) return; // Chatbot widget not on page

  // ── Language Buttons ───────────────────────────────────
  document.querySelectorAll('.chat-lang-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      currentLang = btn.dataset.lang;
      document.querySelectorAll('.chat-lang-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      // Réinitialiser l'historique lors du changement de langue
      conversationHistory = [];

      const confirmMessages = {
        fr: "🇫🇷 Je suis maintenant en <strong>Français</strong>. Posez-moi n'importe quelle question !",
        en: "🇬🇧 I'm now in <strong>English</strong>. Ask me anything!"
      };
      addBotMessage(confirmMessages[currentLang] || confirmMessages.fr);
    });
  });

  // ── Toggle Panel ───────────────────────────────────────
  toggle.addEventListener('click', () => {
    isOpen = !isOpen;
    panel.classList.toggle('open', isOpen);
    iconOpen?.classList.toggle('d-none', isOpen);
    iconClose?.classList.toggle('d-none', !isOpen);
    if (badge) badge.style.display = 'none';
    if (isOpen) {
      setTimeout(() => inputEl?.focus(), 300);
      scrollToBottom();
    }
  });

  closeBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    isOpen = false;
    panel.classList.remove('open');
    iconOpen?.classList.remove('d-none');
    iconClose?.classList.add('d-none');
  });

  // ── Send on Enter ──────────────────────────────────────
  inputEl?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  sendBtn?.addEventListener('click', sendMessage);

  // ── Suggestion Buttons ─────────────────────────────────
  window.sendSuggestion = function (btn) {
    const text = btn.textContent.trim();
    inputEl.value = text;
    sendMessage();
  };

  // ── Core Send Function ─────────────────────────────────
  function sendMessage() {
    const message = inputEl.value.trim();
    if (!message || isTyping) return;

    addUserMessage(message);
    inputEl.value = '';
    showTypingIndicator();

    // Ajouter le message de l'utilisateur à l'historique
    conversationHistory.push({ role: 'user', content: message });

    // Limiter l'historique envoyé (sécurité + performance)
    const historyToSend = conversationHistory.slice(-MAX_HISTORY);

    // Call Flask chatbot API avec historique
    fetch('/api/chatbot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        lang: currentLang,
        history: historyToSend.slice(0, -1) // Exclure le dernier (déjà dans "message")
      })
    })
      .then(res => {
        if (!res.ok) return res.json().then(d => { throw new Error(d.response || 'Erreur serveur'); });
        return res.json();
      })
      .then(data => {
        hideTypingIndicator();

        // Mise à jour langue détectée automatiquement
        if (data.lang && data.lang !== currentLang) {
          currentLang = data.lang;
          document.querySelectorAll('.chat-lang-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.lang === currentLang);
          });
        }

        // Ajouter la réponse de SELA à l'historique
        const plainText = stripHtml(data.response);
        conversationHistory.push({ role: 'assistant', content: plainText });

        // Garder l'historique dans la limite
        if (conversationHistory.length > MAX_HISTORY) {
          conversationHistory = conversationHistory.slice(-MAX_HISTORY);
        }

        addBotMessage(data.response);
      })
      .catch(err => {
        hideTypingIndicator();
        // Retirer le dernier message utilisateur de l'historique en cas d'erreur
        if (conversationHistory.length && conversationHistory[conversationHistory.length - 1].role === 'user') {
          conversationHistory.pop();
        }
        const errorMsgs = {
          fr: "⚠️ Désolé, une erreur est survenue. Veuillez réessayer.",
          en: "⚠️ Sorry, an error occurred. Please try again."
        };
        addBotMessage(err.message || errorMsgs[currentLang] || errorMsgs.fr);
      });
  }

  // ── Message Helpers ────────────────────────────────────
  function addUserMessage(text) {
    const div = document.createElement('div');
    div.className = 'chat-message user-message';
    div.innerHTML = `<div class="message-bubble">${escapeHtml(text)}</div>`;
    messagesEl.appendChild(div);
    scrollToBottom();
    messageCount++;
  }

  function addBotMessage(html) {
    const div = document.createElement('div');
    div.className = 'chat-message bot-message';
    div.innerHTML = `
      <div class="bot-avatar"><i class="fas fa-robot"></i></div>
      <div class="message-bubble">${html}</div>
    `;
    div.style.opacity = '0';
    div.style.transform = 'translateY(10px)';
    messagesEl.appendChild(div);
    // Animate in
    requestAnimationFrame(() => {
      div.style.transition = 'all 0.3s ease';
      div.style.opacity = '1';
      div.style.transform = 'translateY(0)';
    });
    scrollToBottom();
    messageCount++;
  }

  function showTypingIndicator() {
    isTyping = true;
    const div = document.createElement('div');
    div.className = 'chat-message bot-message';
    div.id = 'typingIndicator';
    div.innerHTML = `
      <div class="bot-avatar"><i class="fas fa-robot"></i></div>
      <div class="message-bubble">
        <div class="typing-indicator">
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
        </div>
      </div>
    `;
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function hideTypingIndicator() {
    isTyping = false;
    const indicator = document.getElementById('typingIndicator');
    if (indicator) indicator.remove();
  }

  function scrollToBottom() {
    setTimeout(() => {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }, 50);
  }

  function escapeHtml(str) {
    const d = document.createElement('div');
    d.appendChild(document.createTextNode(str));
    return d.innerHTML;
  }

  // Convertit HTML en texte brut pour l'historique (évite d'envoyer du HTML à Gemini)
  function stripHtml(html) {
    const d = document.createElement('div');
    d.innerHTML = html;
    return d.textContent || d.innerText || '';
  }

  // ── Auto-show badge on page load after delay ───────────
  setTimeout(() => {
    if (!isOpen && badge) {
      badge.style.display = 'flex';
      badge.textContent = '1';
      toggle.style.animation = 'none';
      toggle.offsetHeight; // Force reflow
      toggle.style.boxShadow = '0 0 0 0 rgba(37,99,235,0.7)';
      toggle.animate([
        { boxShadow: '0 0 0 0 rgba(37,99,235,0.7)' },
        { boxShadow: '0 0 0 12px rgba(37,99,235,0)' }
      ], { duration: 1200, iterations: 3 });
    }
  }, 4000);

})();
