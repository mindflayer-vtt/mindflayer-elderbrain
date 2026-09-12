<script setup lang="ts">
const emit = defineEmits<{ complete: [] }>();
const { session, request, refresh, login } = useAdmin();
const password = ref("");
const newPassword = ref("");
const email = ref(session.value.email);
const code = ref("");
const recovery = ref("");
const recovering = ref(false);
const error = ref("");
const notice = ref("");
const busy = ref(false);
const mailSent = ref(false);
const showPassword = ref(false);
const customSmtp = ref(!session.value.defaultSmtpAvailable);
watch(() => session.value.defaultSmtpAvailable, available => { customSmtp.value = !available; });
const smtp = reactive({ host: "", port: 587, secure: false, user: "", password: "", from: "" });
const emailSaved = useUnsavedChanges(() => ({ email: email.value, smtp }));
useUnsavedChanges(() => Boolean(password.value || newPassword.value || code.value || recovery.value));
async function run(task: () => Promise<void>) {
  busy.value = true; error.value = ""; notice.value = "";
  try { await task(); } catch (e) { error.value = e instanceof Error ? e.message : "Request failed"; }
  finally { busy.value = false; }
}
async function signIn() { await login(password.value); password.value = ""; }
async function changePassword() {
  await request("password", { currentPassword: password.value, password: newPassword.value });
  password.value = ""; newPassword.value = "";
  await refresh();
  notice.value = "Password changed. Sign in with your new password.";
}
async function verify() {
  const result = await request<{ recoveryCode: string }>("verify", { code: code.value });
  recovery.value = result.recoveryCode;
  code.value = "";
}
async function finish() { recovery.value = ""; await refresh(); emit("complete"); }
</script>
<template>
  <UContainer class="max-w-xl py-12">
    <UCard>
      <template #header><h1 class="text-2xl font-bold">{{ session.authenticated ? "Administrator account" : "Sign in to Elderbrain" }}</h1></template>
      <div class="space-y-5">
        <UAlert v-if="error" color="error" :title="error" />
        <UAlert v-if="notice" color="success" :title="notice" />
        <template v-if="!session.authenticated">
          <LoginKeyboard />
          <form v-if="!recovering" class="space-y-4" @submit.prevent="run(signIn)">
            <UFormField label="Username"><UInput model-value="admin" readonly autocomplete="username" class="w-full" /></UFormField>
            <UFormField label="Administrator password">
              <SecretInput v-model="password" autocomplete="current-password" required class="w-full" />
            </UFormField>
            <p class="text-sm text-muted">On first boot, find your unique password on the appliance console (Ctrl+Alt+F2), or use <code>elderbrain initial-password</code> over SSH.</p>
            <UButton type="submit" :loading="busy">Sign in</UButton>
            <UButton variant="link" @click="recovering = true">Forgot password?</UButton>
          </form>
          <template v-else>
            <form class="space-y-4" @submit.prevent="run(async () => { await request('recover', { email }); notice = 'If this email is configured, a recovery token has been sent.'; })">
              <UFormField label="Recovery email"><UInput v-model="email" type="email" required class="w-full" /></UFormField>
              <UButton type="submit" :loading="busy">Send recovery token</UButton>
            </form>
            <USeparator label="or use your offline recovery code" />
            <form class="space-y-4" @submit.prevent="run(async () => { await request('reset', { token: code, password: newPassword }); code = ''; newPassword = ''; recovering = false; notice = 'Password reset. Sign in again.'; })">
              <UFormField label="Recovery token or offline code"><SecretInput v-model="code" required class="w-full" /></UFormField>
              <UFormField label="New administrator password"><SecretInput v-model="newPassword" autocomplete="new-password" minlength="12" maxlength="256" required class="w-full" /></UFormField>
              <UButton type="submit" :loading="busy">Reset password</UButton>
              <UButton variant="link" @click="recovering = false">Back to sign in</UButton>
            </form>
          </template>
        </template>
        <template v-else-if="recovery">
          <h2 class="text-xl font-semibold">Save your offline recovery code</h2>
          <p>Keep this code somewhere outside the appliance. It is displayed once and can reset your password if email is unavailable.</p>
          <pre class="break-all whitespace-pre-wrap p-4 bg-elevated rounded">{{ recovery }}</pre>
          <UButton @click="run(finish)">I saved my recovery code</UButton>
        </template>
        <form v-else-if="session.mustChange || showPassword" class="space-y-4" @submit.prevent="run(changePassword)">
          <UAlert title="Set your administrator password" description="The initial password must be changed before continuing." />
          <UFormField label="Current administrator password"><SecretInput v-model="password" autocomplete="current-password" required class="w-full" /></UFormField>
          <UFormField label="New administrator password"><SecretInput v-model="newPassword" autocomplete="new-password" minlength="12" maxlength="256" required class="w-full" /></UFormField>
          <UButton type="submit" :loading="busy">Change password</UButton>
        </form>
        <template v-else>
          <p>Configure and verify a recovery email. SMTP must support TLS. Saved credentials are never returned to this page.</p>
          <form class="space-y-4" @submit.prevent="run(async () => { await request('email', { email, ...(customSmtp ? { smtp } : {}) }); smtp.password = ''; emailSaved(); mailSent = true; notice = 'Verification email sent.'; })">
            <UFormField label="Recovery email"><UInput v-model="email" type="email" required class="w-full" /></UFormField>
            <UCheckbox v-if="session.defaultSmtpAvailable" v-model="customSmtp" label="Use a custom email server" />
            <p v-else class="text-sm text-muted">No default email server was included in this appliance. Enter custom SMTP settings below.</p>
            <p v-if="!customSmtp" class="text-sm text-muted">Using the email server configured for this appliance.</p>
            <div v-if="customSmtp" class="space-y-4">
            <UFormField label="SMTP server"><UInput v-model="smtp.host" required class="w-full" /></UFormField>
            <UFormField label="SMTP port"><UInput v-model.number="smtp.port" type="number" min="1" max="65535" required /></UFormField>
            <UCheckbox v-model="smtp.secure" label="TLS immediately (usually port 465); otherwise require STARTTLS" />
            <UFormField label="SMTP username"><UInput v-model="smtp.user" autocomplete="off" class="w-full" /></UFormField>
            <UFormField label="SMTP password"><SecretInput v-model="smtp.password" autocomplete="new-password" class="w-full" /></UFormField>
            <UFormField label="Sender email"><UInput v-model="smtp.from" type="email" required class="w-full" /></UFormField>
            </div>
            <UButton type="submit" :loading="busy">Test SMTP and send verification</UButton>
          </form>
          <form class="space-y-4" @submit.prevent="run(verify)">
            <UFormField label="Email verification code"><UInput v-model="code" inputmode="numeric" maxlength="6" required class="w-full" /></UFormField>
            <UButton type="submit" :loading="busy">Verify email</UButton>
          </form>
          <div v-if="session.ready" class="flex gap-3">
            <UButton variant="outline" @click="showPassword = true">Change password</UButton>
            <UButton variant="outline" @click="emit('complete')">Return to administration</UButton>
          </div>
        </template>
      </div>
    </UCard>
  </UContainer>
</template>
