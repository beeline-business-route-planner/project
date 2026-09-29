import { useState } from "react";

const SIGN_URL = "https://logo-teka.com/wp-content/uploads/2025/07/beeline-sign-logo.svg";

export function BeelineLogo() {
  const [imageLoaded, setImageLoaded] = useState(false);
  return (
    <div className="beeline-logo" aria-label="билайн — диспетчерская маршрутов">
      <div className="beeline-mark"><svg viewBox="0 0 48 48" aria-hidden="true">
        <defs>
          <clipPath id="beeline-orb">
            <circle cx="24" cy="24" r="21" />
          </clipPath>
        </defs>
        <circle cx="24" cy="24" r="21" fill="#ffe600" />
        <g clipPath="url(#beeline-orb)" fill="#171717">
          <path d="M-2 3h52v7H-2z" />
          <path d="M-2 17h52v7H-2z" />
          <path d="M-2 31h52v7H-2z" />
          <path d="M-2 45h52v7H-2z" />
        </g>
      </svg><img className={`beeline-sign ${imageLoaded ? "loaded" : ""}`} src={SIGN_URL} alt="" onLoad={() => setImageLoaded(true)} /></div>
      <span>
        <strong>билайн</strong>
        <small>диспетчерская</small>
      </span>
    </div>
  );
}
