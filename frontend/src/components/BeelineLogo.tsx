export function BeelineLogo() {
  return (
    <div className="beeline-logo" aria-label="билайн бизнес — диспетчерская маршрутов">
      <svg viewBox="0 0 48 48" aria-hidden="true">
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
      </svg>
      <span>
        <strong>билайн</strong>
        <small>бизнес · маршруты</small>
      </span>
    </div>
  );
}
