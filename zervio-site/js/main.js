// ============================================
// Zervio.ai - Main JavaScript
// ============================================

document.addEventListener('DOMContentLoaded', () => {

    // --- Scroll-based nav styling ---
    const nav = document.querySelector('.nav');
    if (nav) {
        const onScroll = () => {
            nav.classList.toggle('scrolled', window.scrollY > 20);
        };
        window.addEventListener('scroll', onScroll, { passive: true });
        onScroll();
    }

    // --- Mobile nav toggle ---
    const toggle = document.querySelector('.nav-toggle');
    const navLinks = document.querySelector('.nav-links');
    if (toggle && navLinks) {
        toggle.addEventListener('click', () => {
            toggle.classList.toggle('open');
            navLinks.classList.toggle('open');
            document.body.style.overflow = navLinks.classList.contains('open') ? 'hidden' : '';
        });

        // Close on link click
        navLinks.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', () => {
                toggle.classList.remove('open');
                navLinks.classList.remove('open');
                document.body.style.overflow = '';
            });
        });
    }

    // --- Scroll reveal animations ---
    const fadeElements = document.querySelectorAll('.fade-in');
    if (fadeElements.length > 0) {
        const observer = new IntersectionObserver(
            (entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('visible');
                        observer.unobserve(entry.target);
                    }
                });
            },
            { threshold: 0.1, rootMargin: '0px 0px -40px 0px' }
        );

        fadeElements.forEach(el => observer.observe(el));
    }

    // --- Active nav link ---
    const currentPage = window.location.pathname.split('/').pop() || 'index.html';
    document.querySelectorAll('.nav-links a:not(.nav-cta)').forEach(link => {
        const href = link.getAttribute('href');
        if (href === currentPage || (currentPage === '' && href === 'index.html')) {
            link.classList.add('active');
        }
    });

    // --- Typing animation for hero (home page only) ---
    const typingEl = document.querySelector('.typing-text');
    if (typingEl) {
        const phrases = [
            'Takes orders via chat.',
            'Handles phone orders.',
            'Processes SMS orders.',
            'Never misses a detail.',
        ];
        let phraseIndex = 0;
        let charIndex = 0;
        let deleting = false;
        let pauseTimer = null;

        function typeLoop() {
            const current = phrases[phraseIndex];
            if (!deleting) {
                typingEl.textContent = current.substring(0, charIndex + 1);
                charIndex++;
                if (charIndex === current.length) {
                    pauseTimer = setTimeout(() => {
                        deleting = true;
                        typeLoop();
                    }, 2000);
                    return;
                }
                setTimeout(typeLoop, 50);
            } else {
                typingEl.textContent = current.substring(0, charIndex);
                charIndex--;
                if (charIndex < 0) {
                    deleting = false;
                    charIndex = 0;
                    phraseIndex = (phraseIndex + 1) % phrases.length;
                    setTimeout(typeLoop, 400);
                    return;
                }
                setTimeout(typeLoop, 30);
            }
        }

        // Start after a brief delay
        setTimeout(typeLoop, 1000);
    }

    // --- Counter animation for stats ---
    const statNumbers = document.querySelectorAll('.stat-number[data-target]');
    if (statNumbers.length > 0) {
        const counterObserver = new IntersectionObserver(
            (entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        animateCounter(entry.target);
                        counterObserver.unobserve(entry.target);
                    }
                });
            },
            { threshold: 0.5 }
        );

        statNumbers.forEach(el => counterObserver.observe(el));
    }

    function animateCounter(el) {
        const target = parseFloat(el.dataset.target);
        const suffix = el.dataset.suffix || '';
        const prefix = el.dataset.prefix || '';
        const decimal = el.dataset.decimal === 'true';
        const duration = 2000;
        const start = performance.now();

        function update(now) {
            const elapsed = now - start;
            const progress = Math.min(elapsed / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            const value = eased * target;

            if (decimal) {
                el.textContent = prefix + value.toFixed(1) + suffix;
            } else {
                el.textContent = prefix + Math.round(value).toLocaleString() + suffix;
            }

            if (progress < 1) {
                requestAnimationFrame(update);
            }
        }

        requestAnimationFrame(update);
    }

});
