import React from "react";
import { api } from "./api";
import { friendlyError } from "./ui";

function useAuthenticatedMediaState(url: string | null | undefined) {
  const [mediaUrl, setMediaUrl] = React.useState<string>();
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    let active = true;
    let createdUrl: string | undefined;
    setMediaUrl(undefined);
    setError("");
    if (url) {
      api.authenticatedObjectUrl(url).then(value => {
        createdUrl = value;
        if (active) setMediaUrl(value);
        else URL.revokeObjectURL(value);
      }).catch(e => { if (active) setError(friendlyError(e, "load this media preview")); });
    }
    return () => {
      active = false;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [url]);
  return { mediaUrl, error };
}

export function useAuthenticatedMediaUrl(url: string | null | undefined): string | undefined {
  return useAuthenticatedMediaState(url).mediaUrl;
}

type Props = { as: "img" | "audio" | "video"; src: string; posterSrc?: string } & Record<string, any>;

export const AuthenticatedMedia = React.forwardRef<any, Props>(({ as, src, posterSrc, ...props }, ref) => {
  const elementRef = React.useRef<HTMLElement | null>(null);
  const [visible, setVisible] = React.useState(as !== "img" || props.loading !== "lazy");
  React.useEffect(() => {
    if (visible || !elementRef.current) return;
    if (!("IntersectionObserver" in window)) { setVisible(true); return; }
    const observer = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) { setVisible(true); observer.disconnect(); } }, { rootMargin: "240px" });
    observer.observe(elementRef.current);
    return () => observer.disconnect();
  }, [visible]);
  const { mediaUrl, error } = useAuthenticatedMediaState(visible ? src : undefined);
  const { mediaUrl: posterUrl } = useAuthenticatedMediaState(
    visible && as === "video" ? posterSrc : undefined,
  );
  if (error) return <div className="errors" role="alert">{error}</div>;
  return React.createElement(as, {
    ...props, ref: (node: HTMLElement | null): void => { elementRef.current = node; if (typeof ref === "function") ref(node); else if (ref) ref.current = node; }, src: mediaUrl, "aria-busy": !mediaUrl, "data-loading": !mediaUrl,
    ...(as === "video" && posterSrc ? { poster: posterUrl } : {}),
    ...(as === "img" ? { alt: props.alt ?? "Media preview" } : { "aria-label": props["aria-label"] || (as === "audio" ? "Audio preview" : "Video preview") }),
  });
});
