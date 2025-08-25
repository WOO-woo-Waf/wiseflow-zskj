// import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useMutation } from '@tanstack/react-query'

import { Button } from '@/components/ui/button'
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form'
import { Input } from '@/components/ui/input'

import { useLocation, useNavigate } from "react-router-dom";

import { login, registerUser, isAdmin, isUser } from '@/store'
import { useState } from 'react'

export function AdminLoginScreen() {
  const navigate = useNavigate()

  // --- 登录表单 ---
  const form = useForm({
    defaultValues: { username: '', password: '' },
  })

  const loginMut = useMutation({
    mutationFn: login,
    onSuccess: () => {
      // 登录成功：根据角色跳转（现在先统一回首页，你也可以分流到不同页）
      // if (isAdmin()) navigate('/admin'); else navigate('/');
      navigate('/');
    },
  })

  function onSubmitLogin() {
    const { username, password } = form.getValues()
    loginMut.mutate({ username, password })
  }

  // --- 注册表单 ---
  const [showSignup, setShowSignup] = useState(false)
  const signupForm = useForm({
    defaultValues: { email: '', password: '', confirm: '' },
  })

  const signupMut = useMutation({
    mutationFn: async ({ email, password }) => {
      // 1) 创建 PB 用户
      await registerUser({ email, password })
      // 2) 创建成功后自动登录为普通用户
      return await login({ username: email, password })
    },
    onSuccess: () => {
      navigate('/')
    },
  })

  function onSubmitSignup() {
    const { email, password, confirm } = signupForm.getValues()
    if (!email) return signupForm.setError("email", { message: "请填写邮箱" })
    if (!password) return signupForm.setError("password", { message: "请填写密码" })
    if (password !== confirm) return signupForm.setError("confirm", { message: "两次密码不一致" })
    signupMut.mutate({ email, password })
  }

  return (
    <div className="max-w-sm mx-auto text-left">
      <h2 className="mt-10 scroll-m-20 pb-2 text-3xl font-semibold tracking-tight">登录</h2>
      <p className="text-xl text-muted-foreground">输入账号及密码（管理员或普通用户）</p>
      <hr className="my-6" />

      {/* 登录表单 */}
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmitLogin)} className="mx-auto space-y-6">
          <FormField
            control={form.control}
            name="username"
            render={({ field }) => (
              <FormItem>
                <FormLabel>邮箱</FormLabel>
                <FormControl><Input placeholder="you@example.com" {...field} /></FormControl>
                <FormDescription></FormDescription>
                <FormMessage>{loginMut?.error?.message}</FormMessage>
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>密码</FormLabel>
                <FormControl><Input type="password" placeholder="••••••••" {...field} /></FormControl>
                <FormDescription></FormDescription>
                <FormMessage></FormMessage>
              </FormItem>
            )}
          />
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={loginMut.isPending}>
              {loginMut.isPending ? "登录中..." : "登录"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setShowSignup(v => !v)}>
              {showSignup ? "关闭注册" : "创建新用户"}
            </Button>
          </div>
          {loginMut?.isError && <p className="text-sm text-destructive">{String(loginMut.error?.message || "")}</p>}
        </form>
      </Form>

      {/* 注册表单（可折叠） */}
      {showSignup && (
        <>
          <hr className="my-6" />
          <h3 className="text-2xl font-semibold mb-2">创建新用户</h3>
          <p className="text-muted-foreground mb-4">填写邮箱与密码（创建后将自动登录为普通用户）</p>
          <Form {...signupForm}>
            <form onSubmit={signupForm.handleSubmit(onSubmitSignup)} className="space-y-6">
              <FormField
                control={signupForm.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>邮箱</FormLabel>
                    <FormControl><Input placeholder="you@example.com" {...field} /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={signupForm.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>密码</FormLabel>
                    <FormControl><Input type="password" placeholder="至少 6 位" {...field} /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={signupForm.control}
                name="confirm"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>确认密码</FormLabel>
                    <FormControl><Input type="password" placeholder="再次输入密码" {...field} /></FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <div className="flex items-center gap-3">
                <Button type="submit" disabled={signupMut.isPending}>
                  {signupMut.isPending ? "创建中..." : "创建用户并登录"}
                </Button>
                <Button type="button" variant="ghost" onClick={() => setShowSignup(false)}>
                  取消
                </Button>
              </div>
              {signupMut?.isError && <p className="text-sm text-destructive">{String(signupMut.error?.message || "")}</p>}
            </form>
          </Form>
        </>
      )}
    </div>
  )
}

export default AdminLoginScreen
