import type { User } from "firebase/auth";
import { LanguagesIcon, LogOutIcon } from "lucide-react";
import { ThemeModes } from "@/components/ThemeModes";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { signOut } from "@/lib/firebase";
import { SUPPORTED_LANGUAGES, useTranslation } from "@/lib/i18n";

/** The account menu, after the prepza project's: the avatar opens the account, language,
 * sign-out and theme. */
export function UserMenu({ user }: { user: User }) {
  const { t, language, setLanguage } = useTranslation();
  const initial = (user.displayName ?? user.email ?? "?")[0].toUpperCase();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" size="icon" className="rounded-full" aria-label={user.email ?? user.uid} />}
      >
        <Avatar size="sm" className="data-[size=sm]:size-7">
          <AvatarImage src={user.photoURL ?? undefined} alt="" />
          <AvatarFallback>{initial}</AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56 p-2">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-3 py-2">
            {user.displayName && <p className="truncate text-sm text-foreground">{user.displayName}</p>}
            <p className="truncate font-normal">{user.email}</p>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuSub>
          <DropdownMenuSubTrigger className="px-3 py-2">
            <LanguagesIcon />
            {t("language")}
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent>
            <DropdownMenuRadioGroup value={language} onValueChange={(value) => setLanguage(String(value))}>
              {SUPPORTED_LANGUAGES.map((l) => (
                <DropdownMenuRadioItem key={l.code} value={l.code} className="normal-case">
                  {l.label}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="px-3 py-2" variant="destructive" onClick={() => signOut()}>
          <LogOutIcon className="rtl:-scale-x-100" />
          {t("signOut")}
        </DropdownMenuItem>
        <DropdownMenuSeparator className="mb-3" />
        <ThemeModes />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
