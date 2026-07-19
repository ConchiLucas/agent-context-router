"use client";

import { useRouter } from "next/navigation";
import type { MouseEvent } from "react";
import { useState, useTransition } from "react";

type ModalCloseButtonProps = Readonly<{
  href: string;
  className?: string;
}>;

export function ModalCloseButton({ href, className }: ModalCloseButtonProps) {
  const router = useRouter();
  const [isClosing, setIsClosing] = useState(false);
  const [, startTransition] = useTransition();

  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    setIsClosing(true);
    event.currentTarget.closest(".project-modal")?.classList.add("project-modal-closing");
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        startTransition(() => {
          router.push(href);
        });
      });
    });
  }

  return (
    <a
      aria-label="关闭"
      className={[className, isClosing ? "is-pending" : ""].filter(Boolean).join(" ")}
      href={href}
      onClick={handleClick}
      title="关闭"
    >
      ×
    </a>
  );
}
