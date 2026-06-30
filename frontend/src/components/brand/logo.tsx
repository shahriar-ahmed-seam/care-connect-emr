import { cn } from "@/lib/cn";

export function Logo({
  className,
  showWordmark = true,
}: {
  className?: string;
  showWordmark?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <svg
        width="32"
        height="32"
        viewBox="0 0 40 40"
        fill="none"
        role="img"
        aria-label="Care-Connect logo"
      >
        <rect width="40" height="40" rx="10" fill="#0d6e74" />
        <path
          d="M20 9a6 6 0 0 0-6 6v2h-2a6 6 0 1 0 0 12 6 6 0 0 0 6-6v-2h2a6 6 0 1 0 0-12Zm-2 14a4 4 0 0 1-4 4 4 4 0 1 1 0-8h2v2h-0Zm4-6h-2v-2a4 4 0 1 1 4 4h-2v-2Z"
          fill="#ffffff"
        />
        <circle cx="20" cy="20" r="2.4" fill="#e8a13c" />
      </svg>
      {showWordmark && (
        <span className="text-lg font-semibold tracking-tight text-brand-700">
          Care-Connect
        </span>
      )}
    </span>
  );
}
