package com.plantoplate.controller;

import com.plantoplate.model.User;
import com.plantoplate.repository.UserRepository;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSession;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;

@Controller
@RequestMapping("/auth")
public class AuthenticationController {

    private final HttpSession session;
    private final UserRepository userRepository;

    public AuthenticationController(HttpSession session, UserRepository userRepository) {
        this.session = session;
        this.userRepository = userRepository;
    }

    @GetMapping("/login")
    public String showLoginForm(Model model) {
        if (isAuthenticated()) {
            User user = getAuthenticatedUser();
            if (user.getIsTempPassword()) {
                return "redirect:/auth/reset-password";
            }
            return "redirect:/";
        }
        model.addAttribute("message", "Please sign in to continue.");
        return "login";
    }

    @PostMapping("/login")
    public String processLogin(String username, String password, Model model) {
        // Check if already authenticated - redirect to home (no logout)
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.isAuthenticated()) {
            return "redirect:/";
        }

        User user = userRepository.findByUsername(username);

        if (user == null) {
            model.addAttribute("error", "Invalid credentials.");
            return "login";
        }

        boolean isValid = new BCryptPasswordEncoder()
                .matches(password, user.getPasswordHash());

        if (!isValid) {
            model.addAttribute("error", "Invalid credentials.");
            return "login";
        }

        // Set current user in session
        session.setAttribute("currentUser", user);

        // Temp password check - redirect if needed
        if (user.getIsTempPassword()) {
            return "redirect:/auth/reset-password";
        }

        return "redirect:/";
    }

    @GetMapping("/reset-password")
    public String showResetPasswordForm(Model model) {
        if (!isAuthenticated()) {
            return "redirect:/auth/login";
        }

        User currentUser = getAuthenticatedUser();

        try {
            // If has temp password, show form with username from user object
            if (currentUser.getIsTempPassword()) {
                model.addAttribute("username", currentUser.getUsername());
                model.addAttribute("message", "Your temporary password has expired. Please reset it to continue.");
                return "reset-password";
            }

            // Permanent account - still show form but with message
            model.addAttribute("message", "Your permanent account does not require password reset.");
            return "reset-password";
        } catch (Exception e) {}

        // Get username from session for fallback
        Object currentUserObj = session.getAttribute("currentUser");
        if (currentUserObj instanceof User user) {
            model.addAttribute("username", user.getUsername());
        } else {
            model.addAttribute("username", "");
        }
        model.addAttribute("message", "");
        return "reset-password";
    }

    @PostMapping("/reset-password")
    public String processPasswordReset(String currentPassword, String newPassword, Model model) {
        // Get current user from session for logout safety
        Object currentUserObj = session.getAttribute("currentUser");
        if (currentUserObj instanceof User currentUser) {
            return "redirect:/auth/login";
        }

        return "reset-password";
    }



    private boolean isAuthenticated() {
        try {
            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            if (auth != null && auth.isAuthenticated()) {
                Object principal = auth.getPrincipal();
                if (principal instanceof User) {
                    return true;
                }
            }
        } catch (Exception ignored) {}

        Object currentUserObj = session.getAttribute("currentUser");
        if (currentUserObj instanceof User user) {
            return true;
        }
        return false;
    }

    private User getAuthenticatedUser() {
        try {
            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            if (auth != null && auth.getPrincipal() instanceof com.plantoplate.model.User) {
                return ((com.plantoplate.model.User) auth.getPrincipal());
            }
        } catch (Exception ignored) {}

        Object currentUserObj = session.getAttribute("currentUser");
        if (currentUserObj instanceof User user) {
            return user;
        }
        return null;
    }

    private String getAuthenticatedUsername() {
        try {
            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            if (auth != null && auth.getPrincipal() instanceof com.plantoplate.model.User user) {
                return user.getUsername();
            }
        } catch (Exception ignored) {}

        Object currentUserObj = session.getAttribute("currentUser");
        if (currentUserObj instanceof User user) {
            return user.getUsername();
        }
        return null;
    }
}
