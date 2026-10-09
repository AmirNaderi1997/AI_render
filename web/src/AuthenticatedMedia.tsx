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

type Props = { as: "img" | "audio" | "video"; src: string } & Record<string, any>;

export const AuthenticatedMedia = React.forwardRef<any, Props>(({ as, src, ...props }, ref) => {
  const { mediaUrl, error } = useAuthenticatedMediaState(src);
  if (error) return <div className="errors" role="alert">{error}</div>;
  return React.createElement(as, {
    ...props, ref, src: mediaUrl, "aria-busy": !mediaUrl, "data-loading": !mediaUrl,
    ...(as === "img" ? { alt: props.alt || "Media preview" } : { "aria-label": props["aria-label"] || (as === "audio" ? "Audio preview" : "Video preview") }),
  });
});
