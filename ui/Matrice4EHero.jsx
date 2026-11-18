import React, { useEffect, useRef } from "react";

const VIDEO_SRC =
  "https://www-cdn.djiits.com/reactor/assets/_next/static/videos/82111ccc-84ca-4b38-b138-43fac4556f60.mp4";

export default function Matrice4EHero() {
  const videoRef = useRef(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return undefined;

    video.muted = true;
    video.defaultMuted = true;
    video.playsInline = true;

    const resumePlayback = () => {
      if (!video) return;
      video.muted = true;
      try {
        const playPromise = video.play();
        if (playPromise && typeof playPromise.catch === "function") {
          playPromise.catch(() => {});
        }
      } catch (_) {}
    };

    const handleVisibilityChange = () => {
      if (!document.hidden || video.paused) {
        resumePlayback();
      }
    };

    resumePlayback();

    const mediaEvents = ["pause", "ended", "loadedmetadata", "canplay"];
    mediaEvents.forEach((evt) => video.addEventListener(evt, resumePlayback));
    document.addEventListener("visibilitychange", handleVisibilityChange);

    const watchdogId = window.setInterval(() => {
      if (video.paused || video.ended) {
        resumePlayback();
      }
    }, 1000);

    return () => {
      window.clearInterval(watchdogId);
      mediaEvents.forEach((evt) => video.removeEventListener(evt, resumePlayback));
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&display=swap');

        *, *::before, *::after {
          margin: 0;
          padding: 0;
          box-sizing: border-box;
        }

        html, body {
          overflow-x: hidden;
          max-width: 100vw;
          background: #0a0a0b;
          font-family: 'Archivo', sans-serif;
          -webkit-font-smoothing: antialiased;
        }

        .m4e-hero a {
          text-decoration: none;
          color: inherit;
          transition: color 0.2s ease, background-color 0.2s ease, border-color 0.2s ease;
        }

        .m4e-hero a:hover {
          color: #fff;
        }

        .m4e-hero {
          position: relative;
          width: 100%;
          height: 100vh;
          min-height: 720px;
          overflow: hidden;
          background: #0a0a0b;
          font-family: 'Archivo', sans-serif;
          color: #fff;
        }

        .m4e-video {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          object-fit: cover;
          object-position: center 60%;
          pointer-events: none;
          z-index: 0;
        }

        .m4e-overlay {
          position: absolute;
          inset: 0;
          background: linear-gradient(
            180deg,
            rgba(8, 8, 10, 0.55) 0%,
            rgba(8, 8, 10, 0.15) 30%,
            rgba(8, 8, 10, 0.25) 55%,
            rgba(8, 8, 10, 0.92) 100%
          );
          pointer-events: none;
          z-index: 1;
        }

        .m4e-navbar {
          position: relative;
          z-index: 3;
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 34px 56px;
        }

        .m4e-nav-links {
          display: flex;
          align-items: center;
          gap: 42px;
          font-size: 14px;
          font-weight: 500;
          color: rgba(255, 255, 255, 0.82);
        }

        .m4e-nav-links a.active {
          color: #fff;
          border-bottom: 2px solid #fff;
          padding-bottom: 3px;
        }

        .m4e-logo {
          color: #fff;
          font-size: 26px;
          font-weight: 700;
          letter-spacing: 0.04em;
          white-space: nowrap;
        }

        .m4e-quote-btn {
          display: inline-flex;
          align-items: center;
          gap: 10px;
          background: rgba(255, 255, 255, 0.08);
          border: 1px solid rgba(255, 255, 255, 0.2);
          color: #FAF9F5;
          font-family: 'Archivo', sans-serif;
          font-size: 14px;
          font-weight: 600;
          padding: 11px 20px;
          border-radius: 10px;
          cursor: pointer;
          transition: background-color 0.2s ease, color 0.2s ease, border-color 0.2s ease;
        }

        .m4e-quote-btn .m4e-arrow {
          font-size: 15px;
          line-height: 1;
        }

        .m4e-quote-btn:hover {
          background: #e9e9ec;
          color: #0a0a0b;
        }

        .m4e-giant-headline {
          position: absolute;
          top: 92px;
          left: 0;
          width: 100%;
          text-align: center;
          z-index: 2;
          font-size: 13.3vw;
          font-weight: 800;
          line-height: 0.9;
          letter-spacing: -0.03em;
          white-space: nowrap;
          background: linear-gradient(180deg, #ffffff 55%, #b8b8bd 100%);
          -webkit-background-clip: text;
          background-clip: text;
          -webkit-text-fill-color: transparent;
          color: transparent;
          pointer-events: none;
          user-select: none;
        }

        .m4e-bottom-copy {
          position: absolute;
          left: 56px;
          bottom: 56px;
          z-index: 3;
          max-width: 620px;
        }

        .m4e-subheadline {
          color: #fff;
          font-weight: 600;
          font-size: clamp(38px, 5.8vw, 66px);
          line-height: 0.98;
          letter-spacing: -0.02em;
        }

        .m4e-description {
          color: rgba(255, 255, 255, 0.82);
          font-size: 15px;
          font-weight: 400;
          line-height: 1.5;
          max-width: 480px;
          margin-top: 18px;
        }

        .m4e-specs-btn {
          display: inline-flex;
          align-items: center;
          gap: 12px;
          margin-top: 32px;
          background: rgba(255, 255, 255, 0.08);
          border: 1px solid rgba(255, 255, 255, 0.2);
          -webkit-backdrop-filter: blur(6px);
          backdrop-filter: blur(6px);
          color: #fff;
          font-family: 'Archivo', sans-serif;
          font-size: 14px;
          font-weight: 600;
          letter-spacing: 0.04em;
          padding: 13px 24px;
          border-radius: 10px;
          cursor: pointer;
          transition: background-color 0.2s ease, color 0.2s ease, border-color 0.2s ease;
        }

        .m4e-specs-btn .m4e-arrow {
          font-size: 15px;
          line-height: 1;
        }

        .m4e-specs-btn:hover {
          background: #fff;
          color: #0a0a0b;
          border-color: #fff;
        }
      `}</style>

      <section className="m4e-hero">
        <video
          ref={videoRef}
          className="m4e-video"
          src={VIDEO_SRC}
          autoPlay
          muted
          loop
          playsInline
          preload="auto"
        />

        <div className="m4e-overlay" />

        <nav className="m4e-navbar">
          <div className="m4e-nav-links">
            <a href="#overview" className="active">Overview</a>
            <a href="#matrice-4e">Matrice 4E</a>
            <a href="#payloads">Payloads</a>
            <a href="#software">Software</a>
          </div>

          <a href="#dji-enterprise" className="m4e-logo">
            DJI ENTERPRISE
          </a>

          <a href="#request-quote" className="m4e-quote-btn">
            <span>Request Quote</span>
            <span className="m4e-arrow">→</span>
          </a>
        </nav>

        <h1 className="m4e-giant-headline">MATRICE 4E</h1>

        <div className="m4e-bottom-copy">
          <h2 className="m4e-subheadline">Next-Gen Precision Aerial Surveying</h2>
          <p className="m4e-description">
            Engineered for centimeter-level accuracy, mission-critical reliability, and seamless high-efficiency photogrammetry workflows.
          </p>
          <a href="#explore-specs" className="m4e-specs-btn">
            <span>EXPLORE SPECS</span>
            <span className="m4e-arrow">↗</span>
          </a>
        </div>
      </section>
    </>
  );
}
