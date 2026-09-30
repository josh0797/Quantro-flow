import React from 'react';
import { ShieldCheck } from 'lucide-react';
import { useLanguage } from '../context/LanguageContext';
import LanguageSwitcher from './LanguageSwitcher';

/**
 * AuthCardShell — centered single-card layout for the small auth screens
 * (forgot password, set a new password). Same brand mark, language switch
 * and footer as LoginPage's action panel.
 */
export default function AuthCardShell({ children, testId }) {
  const { t } = useLanguage();
  return (
    <div
      data-testid={testId}
      className="min-h-screen w-full flex flex-col items-center justify-center p-8 md:p-12 bg-background text-foreground relative"
    >
      <div className="absolute top-4 right-4">
        <LanguageSwitcher />
      </div>
      <div className="w-full max-w-sm space-y-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] flex items-center justify-center font-bold">
            Q
          </div>
          <div className="text-lg font-semibold tracking-tight">Quantro Flow</div>
        </div>
        {children}
        <div className="flex items-center gap-2 text-xs text-muted-foreground pt-2 border-t border-[hsl(var(--border))]">
          <ShieldCheck size={14} className="text-[hsl(var(--success))]" />
          <span>{t('auth.secure_session')} · {t('auth.secured_by')}</span>
        </div>
      </div>
    </div>
  );
}
