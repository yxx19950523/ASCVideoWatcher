FIRST_MEDIA_STATUS_SCRIPT = r"""
({ planIndex, planSelector, mediaSelector, placeholderSelector, previewSelector }) => {
  const isVisible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width >= 20 && rect.height >= 20;
  };

  const textOf = (el) => [
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || '',
    el.textContent || ''
  ].join(' ').trim();

  const queryVisible = (root, selector) => {
    if (!selector) return [];
    try {
      return Array.from(root.querySelectorAll(selector)).filter(isVisible);
    } catch (_) {
      return [];
    }
  };

  const findPlans = () => {
    if (planSelector) {
      const custom = queryVisible(document, planSelector);
      if (custom.length) return custom;
    }
    const seen = new Set();
    const plans = [];
    const addPlan = (el) => {
      if (!el || seen.has(el)) return;
      seen.add(el);
      plans.push(el);
    };
    const climbToPlan = (el) => {
      let node = el;
      for (let i = 0; node && i < 10; i += 1, node = node.parentElement) {
        if (!isVisible(node)) continue;
        const rect = node.getBoundingClientRect();
        const text = textOf(node);
        if (rect.width > 500 && rect.height > 130 && /选择文件|全部删除|App 预览|张截屏|截图|测试方案/.test(text)) {
          return node;
        }
      }
      return null;
    };
    Array.from(document.querySelectorAll('button, [role="button"], a, label, span, div')).forEach((el) => {
      const text = textOf(el);
      if (/选择文件|全部删除|App 预览|张截屏|截图|测试方案/.test(text) || /\d+\s*\/\s*\d+\s*个\s*App\s*预览/.test(text)) {
        addPlan(climbToPlan(el));
      }
    });
    return plans.sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return ar.top - br.top || ar.left - br.left;
    });
  };

  const findFirstMedia = (plan) => {
    if (mediaSelector) {
      const custom = queryVisible(plan, mediaSelector);
      if (custom.length) return custom[0];
    }
    const planRect = plan.getBoundingClientRect();
    const items = Array.from(plan.querySelectorAll('div, button, figure, img, canvas, video, picture')).filter((el) => {
      if (!isVisible(el)) return false;
      const rect = el.getBoundingClientRect();
      const text = textOf(el);
      if (rect.width < 90 || rect.height < 60) return false;
      if (rect.left < planRect.left - 2 || rect.right > planRect.right + 2) return false;
      if (/选择文件|全部删除|App 预览|张截屏/.test(text) && rect.height < 90) return false;
      return rect.top > planRect.top + 20 && rect.bottom < planRect.bottom - 20;
    });
    const sorted = items.sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return ar.top - br.top || ar.left - br.left || (br.width * br.height) - (ar.width * ar.height);
    });
    return sorted[0] || null;
  };

  const plans = findPlans();
  const plan = plans[Math.max(0, Number(planIndex) || 0)] || null;
  if (!plan) {
    const bodyText = document.body ? document.body.innerText || '' : '';
    return {
      phase: 'waiting',
      reason: '没有找到测试方案',
      planCount: 0,
      chooseFileCount: (bodyText.match(/选择文件/g) || []).length,
      previewCounterCount: (bodyText.match(/\d+\s*\/\s*\d+\s*个\s*App\s*预览/g) || []).length,
      testPlanTextCount: (bodyText.match(/测试方案/g) || []).length
    };
  }

  const media = findFirstMedia(plan);
  const planText = textOf(plan);
  const previewCounter = planText.match(/(\d+)\s*\/\s*\d+\s*个\s*App\s*预览/);
  const appPreviewCount = previewCounter ? Number(previewCounter[1]) : null;
  if (appPreviewCount === 0) {
    return {
      phase: 'no_video',
      reason: '测试方案中没有 App 预览视频',
      planCount: plans.length,
      appPreviewCount
    };
  }

  if (!media) {
    return { phase: 'waiting', reason: '没有找到第一位媒体', planCount: plans.length, appPreviewCount };
  }

  const customPlaceholder = placeholderSelector ? queryVisible(media, placeholderSelector).length : 0;
  const customPreview = previewSelector ? queryVisible(media, previewSelector).length : 0;
  const rect = media.getBoundingClientRect();
  const style = getComputedStyle(media);
  const bg = style.backgroundColor || '';
  const label = textOf(media);
  const cls = String(media.className || '');

  const gray = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  const looksGray = gray &&
    Math.abs(+gray[1] - +gray[2]) < 15 &&
    Math.abs(+gray[2] - +gray[3]) < 15 &&
    +gray[1] >= 130 &&
    +gray[1] <= 245;
  const hasCloudOrProcessing = /cloud|upload|placeholder|skeleton|processing|正在|处理|占位|上传/i.test(label + ' ' + cls + ' ' + media.innerHTML);
  const hasVideoPreview = media.querySelector('video, canvas, img, picture') ||
    /预览|播放|play|preview|poster|thumbnail|video|App 预览/i.test(label + ' ' + cls + ' ' + media.innerHTML);

  let phase = 'waiting';
  if (customPlaceholder || (looksGray && hasCloudOrProcessing)) phase = 'placeholder';
  else if (customPreview || hasVideoPreview) phase = 'ready';

  return {
    phase,
    reason: '',
    planCount: plans.length,
    appPreviewCount,
    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
    text: label.slice(0, 120),
    background: bg
  };
}
"""


REMOVE_FIRST_MEDIA_SCRIPT = r"""
({ planIndex, planSelector, mediaSelector, removeSelector, confirmSelector }) => {
  const isVisible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width >= 8 && rect.height >= 8;
  };

  const textOf = (el) => [
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || '',
    el.textContent || ''
  ].join(' ').trim();

  const queryVisible = (root, selector) => {
    if (!selector) return [];
    try {
      return Array.from(root.querySelectorAll(selector)).filter(isVisible);
    } catch (_) {
      return [];
    }
  };

  const findPlans = () => {
    if (planSelector) {
      const custom = queryVisible(document, planSelector);
      if (custom.length) return custom;
    }
    const seen = new Set();
    const plans = [];
    const addPlan = (el) => {
      if (!el || seen.has(el)) return;
      seen.add(el);
      plans.push(el);
    };
    const climbToPlan = (el) => {
      let node = el;
      for (let i = 0; node && i < 10; i += 1, node = node.parentElement) {
        if (!isVisible(node)) continue;
        const rect = node.getBoundingClientRect();
        const text = textOf(node);
        if (rect.width > 500 && rect.height > 130 && /选择文件|全部删除|App 预览|张截屏|截图|测试方案/.test(text)) {
          return node;
        }
      }
      return null;
    };
    Array.from(document.querySelectorAll('button, [role="button"], a, label, span, div')).forEach((el) => {
      const text = textOf(el);
      if (/选择文件|全部删除|App 预览|张截屏|截图|测试方案/.test(text) || /\d+\s*\/\s*\d+\s*个\s*App\s*预览/.test(text)) {
        addPlan(climbToPlan(el));
      }
    });
    return plans.sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return ar.top - br.top || ar.left - br.left;
    });
  };

  const findFirstMedia = (plan) => {
    if (mediaSelector) {
      const custom = queryVisible(plan, mediaSelector);
      if (custom.length) return custom[0];
    }
    const planRect = plan.getBoundingClientRect();
    return Array.from(plan.querySelectorAll('div, button, figure, img, canvas, video, picture')).filter((el) => {
      if (!isVisible(el)) return false;
      const rect = el.getBoundingClientRect();
      const text = textOf(el);
      if (rect.width < 90 || rect.height < 60) return false;
      if (rect.left < planRect.left - 2 || rect.right > planRect.right + 2) return false;
      if (/选择文件|全部删除|App 预览|张截屏/.test(text) && rect.height < 90) return false;
      return rect.top > planRect.top + 20 && rect.bottom < planRect.bottom - 20;
    }).sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return ar.top - br.top || ar.left - br.left || (br.width * br.height) - (ar.width * ar.height);
    })[0] || null;
  };

  const plans = findPlans();
  const plan = plans[Math.max(0, Number(planIndex) || 0)] || null;
  if (!plan) return { ok: false, message: '没有找到第一个测试方案' };
  const media = findFirstMedia(plan);
  if (!media) return { ok: false, message: '没有找到第一位媒体' };

  media.scrollIntoView({ block: 'center', inline: 'center' });
  for (const type of ['mouseover', 'mouseenter', 'mousemove']) {
    media.dispatchEvent(new MouseEvent(type, { bubbles: true, clientX: media.getBoundingClientRect().left + 8, clientY: media.getBoundingClientRect().top + 8 }));
  }

  const mediaRect = media.getBoundingClientRect();
  const clickButton = (button) => {
    button.click();
    setTimeout(() => {
      let confirm = queryVisible(document, confirmSelector)[0];
      if (!confirm) {
        confirm = Array.from(document.querySelectorAll('button, [role="button"]')).filter((el) => {
          if (!isVisible(el) || el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
          return /删除|移除|确认|delete|remove|ok|yes/i.test(textOf(el));
        }).pop();
      }
      if (confirm) confirm.click();
    }, 700);
    return { ok: true, message: textOf(button) || '已点击移除按钮' };
  };

  const customRemove = queryVisible(document, removeSelector)[0];
  if (customRemove) return clickButton(customRemove);

  const candidates = Array.from(document.querySelectorAll('button, [role="button"], a')).filter((el) => {
    if (!isVisible(el) || el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
    const rect = el.getBoundingClientRect();
    const text = textOf(el);
    const style = getComputedStyle(el);
    const bg = style.backgroundColor || '';
    const red = /rgb\((1[5-9]\d|2[0-5]\d),\s*([0-8]?\d),\s*([0-8]?\d)\)/.test(bg);
    const nearTopLeft = rect.left >= mediaRect.left - 28 &&
      rect.left <= mediaRect.left + 48 &&
      rect.top >= mediaRect.top - 28 &&
      rect.top <= mediaRect.top + 48;
    return nearTopLeft && (red || /删除|移除|remove|delete/i.test(text));
  });

  if (candidates.length) return clickButton(candidates[0]);
  return { ok: false, message: '悬停后没有找到左上角红色移除按钮' };
}
"""


CLICK_UPLOAD_BUTTON_SCRIPT = r"""
({ planIndex, planSelector, uploadButtonSelector }) => {
  const isVisible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width >= 8 && rect.height >= 8;
  };

  const textOf = (el) => [
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || '',
    el.textContent || ''
  ].join(' ').trim();

  const queryVisible = (root, selector) => {
    if (!selector) return [];
    try {
      return Array.from(root.querySelectorAll(selector)).filter(isVisible);
    } catch (_) {
      return [];
    }
  };

  const findPlans = () => {
    if (planSelector) {
      const custom = queryVisible(document, planSelector);
      if (custom.length) return custom;
    }
    const seen = new Set();
    const plans = [];
    const addPlan = (el) => {
      if (!el || seen.has(el)) return;
      seen.add(el);
      plans.push(el);
    };
    const climbToPlan = (el) => {
      let node = el;
      for (let i = 0; node && i < 10; i += 1, node = node.parentElement) {
        if (!isVisible(node)) continue;
        const rect = node.getBoundingClientRect();
        const text = textOf(node);
        if (rect.width > 500 && rect.height > 130 && /选择文件|全部删除|App 预览|张截屏|截图|测试方案/.test(text)) {
          return node;
        }
      }
      return null;
    };
    Array.from(document.querySelectorAll('button, [role="button"], a, label, span, div')).forEach((el) => {
      const text = textOf(el);
      if (/选择文件|全部删除|App 预览|张截屏|截图|测试方案/.test(text) || /\d+\s*\/\s*\d+\s*个\s*App\s*预览/.test(text)) {
        addPlan(climbToPlan(el));
      }
    });
    return plans.sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return ar.top - br.top || ar.left - br.left;
    });
  };

  const plans = findPlans();
  const plan = plans[Math.max(0, Number(planIndex) || 0)] || null;
  if (!plan) return { ok: false, message: '没有找到测试方案' };

  let button = queryVisible(plan, uploadButtonSelector)[0];
  if (!button) {
    button = Array.from(plan.querySelectorAll('button, [role="button"], a, label')).filter((el) => {
      if (!isVisible(el) || el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
      return /选择文件|上传|choose file|upload/i.test(textOf(el));
    }).sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return ar.top - br.top || ar.left - br.left;
    })[0];
  }

  if (!button) return { ok: false, message: '没有找到“选择文件”按钮' };
  button.scrollIntoView({ block: 'center', inline: 'center' });
  button.click();
  return { ok: true, message: textOf(button) || '已点击选择文件按钮' };
}
"""
