import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react';
import { gsap } from 'gsap';

import { designTokens } from './designTokens';

export function useWorkspacePageMotion(root: RefObject<HTMLElement | null>, route: string) {
  const previousRoute = useRef(route);
  useLayoutEffect(() => {
    if (previousRoute.current === route) return;
    previousRoute.current = route;
    const content = root.current?.querySelector<HTMLElement>('.route-pane-active .content');
    if (!content) return;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      gsap.fromTo(content, { opacity: 0.72, x: 8 }, {
        opacity: 1, x: 0, duration: designTokens.motion.page,
        ease: 'power2.out', clearProps: 'opacity,transform',
      });
    }, content);
    return () => media.revert();
  }, [root, route]);
}

export function useFilterPopoverMotion(root: RefObject<HTMLDivElement | null>, open: boolean) {
  useEffect(() => {
    if (!open) return;
    const media = gsap.matchMedia();
    // The portal mounts after the trigger; animate its content, never its positioner.
    const frame = requestAnimationFrame(() => {
      const content = root.current;
      if (!content) return;
      media.add('(prefers-reduced-motion: no-preference)', () => {
        gsap.fromTo(content, { opacity: 0.5, y: -6 }, {
          opacity: 1, y: 0, duration: designTokens.motion.popover,
          ease: 'power2.out', clearProps: 'opacity,transform',
        });
      }, content);
    });
    return () => { cancelAnimationFrame(frame); media.revert(); };
  }, [root, open]);
}
