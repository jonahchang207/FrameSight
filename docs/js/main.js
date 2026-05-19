(function () {
  const repo = window.FRAMESIGHT_REPO || "https://github.com/jonahchang/FrameSight";

  ["githubLink", "footerGh", "setupLink"].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (id === "setupLink") el.href = repo + "/blob/main/SETUP.md";
    else el.href = repo;
  });

  const footerSetup = document.getElementById("footerSetup");
  const footerTrain = document.getElementById("footerTrain");
  if (footerSetup) footerSetup.href = repo + "/blob/main/SETUP.md";
  if (footerTrain) footerTrain.href = repo + "/blob/main/TRAIN.md";

  // Typed hero
  const phrases = ["Understand it.", "Detect live.", "Assist clearly."];
  const typed = document.getElementById("typed");
  let pi = 0,
    ci = 0,
    deleting = false;

  function tick() {
    const phrase = phrases[pi];
    if (!deleting) {
      typed.textContent = phrase.slice(0, ++ci);
      if (ci === phrase.length) {
        deleting = true;
        setTimeout(tick, 1800);
        return;
      }
    } else {
      typed.textContent = phrase.slice(0, --ci);
      if (ci === 0) {
        deleting = false;
        pi = (pi + 1) % phrases.length;
      }
    }
    setTimeout(tick, deleting ? 40 : 70);
  }
  if (typed) tick();

  // Scroll reveal
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) e.target.classList.add("visible");
      });
    },
    { threshold: 0.12 }
  );
  document.querySelectorAll(".reveal").forEach((el) => observer.observe(el));

  // Animated stats
  function animateStat(el) {
    const target = +el.dataset.target;
    const suffix = el.dataset.suffix || "";
    const duration = 1600;
    const start = performance.now();
    function frame(now) {
      const t = Math.min((now - start) / duration, 1);
      const ease = 1 - Math.pow(1 - t, 3);
      const val = Math.floor(ease * target);
      el.textContent = val.toLocaleString() + suffix;
      if (t < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  const statsObs = new IntersectionObserver(
    (entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        e.target.querySelectorAll(".stat-val").forEach(animateStat);
        statsObs.unobserve(e.target);
      });
    },
    { threshold: 0.5 }
  );
  const statsEl = document.querySelector(".hero-stats");
  if (statsEl) statsObs.observe(statsEl);

  // Mobile menu
  const menuBtn = document.getElementById("menuBtn");
  const navLinks = document.getElementById("navLinks");
  if (menuBtn && navLinks) {
    menuBtn.addEventListener("click", () => navLinks.classList.toggle("open"));
  }

  // Animated mesh background
  const canvas = document.getElementById("mesh");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  let w, h, t = 0;

  function resize() {
    w = canvas.width = window.innerWidth;
    h = canvas.height = window.innerHeight;
  }
  window.addEventListener("resize", resize);
  resize();

  function draw() {
    t += 0.004;
    ctx.fillStyle = "#06080f";
    ctx.fillRect(0, 0, w, h);
    for (let i = 0; i < 5; i++) {
      const x = w * (0.2 + 0.15 * i + 0.08 * Math.sin(t + i));
      const y = h * (0.3 + 0.1 * Math.cos(t * 0.7 + i * 1.2));
      const g = ctx.createRadialGradient(x, y, 0, x, y, w * 0.35);
      g.addColorStop(0, i % 2 ? "rgba(61,255,168,0.07)" : "rgba(91,140,255,0.06)");
      g.addColorStop(1, "transparent");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    }
    requestAnimationFrame(draw);
  }
  draw();
})();
