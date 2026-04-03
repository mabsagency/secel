// ═══════════════════════════════════════════════════════
// SECEL — Main JavaScript
// ═══════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', function () {

  // ── Mobile Sidebar ────────────────────────────────────
  const mobileToggle = document.getElementById('mobileSidebarToggle');
  const mobileSidebar = document.getElementById('mobileSidebar');
  const mobileOverlay = document.getElementById('mobileOverlay');
  const mobileClose = document.getElementById('mobileSidebarClose');

  function openMobileMenu() {
    mobileSidebar?.classList.add('open');
    mobileOverlay?.classList.add('show');
    document.body.style.overflow = 'hidden';
  }
  function closeMobileMenu() {
    mobileSidebar?.classList.remove('open');
    mobileOverlay?.classList.remove('show');
    document.body.style.overflow = '';
  }

  mobileToggle?.addEventListener('click', openMobileMenu);
  mobileClose?.addEventListener('click', closeMobileMenu);
  mobileOverlay?.addEventListener('click', closeMobileMenu);

  // ── Flash Message Auto-dismiss ─────────────────────────
  document.querySelectorAll('.flash-alert').forEach(alert => {
    setTimeout(() => {
      alert.style.transition = 'all 0.4s ease';
      alert.style.opacity = '0';
      alert.style.transform = 'translateX(100%)';
      setTimeout(() => alert.remove(), 400);
    }, 5000);
  });

  // ── Navbar scroll effect ──────────────────────────────
  const navbar = document.getElementById('mainNav');
  if (navbar) {
    window.addEventListener('scroll', () => {
      if (window.scrollY > 50) {
        navbar.style.background = 'rgba(255,255,255,0.98)';
        navbar.style.borderBottomColor = 'rgba(37,99,235,0.2)';
      } else {
        navbar.style.background = 'rgba(255,255,255,0.95)';
        navbar.style.borderBottomColor = 'rgba(226,232,240,1)';
      }
    }, { passive: true });
  }

  // ── Smooth scroll for anchor links ───────────────────
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
      const target = document.querySelector(this.getAttribute('href'));
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

  // ── Intersection Observer: animate elements on scroll ─
  const animatedEls = document.querySelectorAll('.how-card, .course-card, .testimonial-card, .kpi-card, .mini-kpi');
  if (animatedEls.length && 'IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.style.opacity = '1';
          entry.target.style.transform = 'translateY(0)';
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

    animatedEls.forEach(el => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(20px)';
      el.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
      io.observe(el);
    });
  }

  // ── Upload form progress ───────────────────────────────
  const uploadForm = document.getElementById('uploadForm');
  const uploadBtn = document.getElementById('uploadBtn');
  if (uploadForm && uploadBtn) {
    uploadForm.addEventListener('submit', function () {
      uploadBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i> Upload en cours...';
      uploadBtn.disabled = true;
    });
  }

  // ── Drag-over visual feedback on upload zones ─────────
  document.querySelectorAll('.upload-zone').forEach(zone => {
    zone.addEventListener('dragover', e => {
      e.preventDefault();
      zone.style.borderColor = 'var(--gold)';
      zone.style.background = 'rgba(37,99,235,0.05)';
    });
    zone.addEventListener('dragleave', () => {
      zone.style.borderColor = '';
      zone.style.background = '';
    });
    zone.addEventListener('drop', () => {
      zone.style.borderColor = '';
      zone.style.background = '';
    });
  });

  // ── Tooltips ──────────────────────────────────────────
  const tooltipEls = document.querySelectorAll('[title]');
  tooltipEls.forEach(el => {
    if (typeof bootstrap !== 'undefined') {
      new bootstrap.Tooltip(el, { trigger: 'hover', placement: 'top' });
    }
  });

  // ── Notification mark as read (click on item) ─────────
  document.querySelectorAll('.notif-item[data-id]').forEach(item => {
    item.addEventListener('click', () => {
      fetch(`/notifications/mark-read/${item.dataset.id}`, { method: 'POST' })
        .then(() => { item.style.opacity = '0.5'; });
    });
  });

  // ── i18n simple text switcher ─────────────────────────
  const TRANSLATIONS = {
    fr: {
      hero_badge: "Plateforme #1 de Formation Professionnelle",
      hero_title: "Construisez votre <span class='text-gold'>Excellence</span><br/>avec SECEL",
      hero_subtitle: "Accédez à des formations premium par vidéo, PDF et cours interactifs. Apprenez avec les meilleurs enseignants, à votre rythme.",
      start_free: "Commencer Gratuitement",
      explore_courses: "Explorer les Cours",
      trust_text: "+500 étudiants nous font confiance",
      about_label: "À Propos de SECEL",
      about_title: "L'Excellence au Service<br/>de Votre <span class='text-gold'>Formation</span>",
      stat_students: "Étudiants inscrits",
      stat_teachers: "Enseignants experts",
      stat_courses: "Cours disponibles",
      stat_videos: "Vidéos de formation",
      join_us: "Rejoindre SECEL",
      courses_label: "Nos Formations",
      courses_title: "Cours <span class='text-gold'>Populaires</span>",
      see_all: "Voir tout",
      cta_title: "Prêt à transformer votre avenir ?",
      cta_btn1: "Commencer maintenant",
      cta_btn2: "Voir les cours",
      access_course: "Accéder au cours"
    },
    en: {
      hero_badge: "The #1 Professional Training Platform",
      hero_title: "Build your <span class='text-gold'>Excellence</span><br/>with SECEL",
      hero_subtitle: "Access premium training through video, PDF, and interactive courses. Learn with the best teachers at your own pace.",
      start_free: "Start for Free",
      explore_courses: "Explore Courses",
      trust_text: "+500 students trust us",
      about_label: "About SECEL",
      about_title: "Excellence in Service<br/>of Your <span class='text-gold'>Education</span>",
      stat_students: "Enrolled students",
      stat_teachers: "Expert teachers",
      stat_courses: "Available courses",
      stat_videos: "Training videos",
      join_us: "Join SECEL",
      courses_label: "Our Programs",
      courses_title: "<span class='text-gold'>Popular</span> Courses",
      see_all: "See all",
      cta_title: "Ready to transform your future?",
      cta_btn1: "Start now",
      cta_btn2: "See courses",
      access_course: "Access course"
    },
  };

  // Get current language from the page
  const htmlLang = document.documentElement.lang || 'fr';

  function applyTranslations(lang) {
    const t = TRANSLATIONS[lang];
    if (!t) return;
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.dataset.i18n;
      if (t[key] !== undefined) {
        el.innerHTML = t[key];
      }
    });
  }

  // Apply on page load
  if (htmlLang && TRANSLATIONS[htmlLang]) {
    applyTranslations(htmlLang);
  }

  // ── Table filter utility (exposed globally) ───────────
  window.filterTable = function (input, tableId) {
    const filter = input.value.toLowerCase();
    const rows = document.getElementById(tableId)?.querySelectorAll('tbody tr');
    rows?.forEach(row => {
      row.style.display = row.textContent.toLowerCase().includes(filter) ? '' : 'none';
    });
  };

});
