package com.plantoplate.filter;

import jakarta.servlet.*;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpSession;
import java.io.IOException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.stereotype.Component;
import com.plantoplate.model.User;

@Component
public class TempPasswordInterceptor implements Filter {

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws ServletException, IOException {

        HttpServletRequest httpRequest = (HttpServletRequest) request;
        HttpServletResponse httpResponse = (HttpServletResponse) response;

        // Skip auth controller endpoints
        String path = httpRequest.getRequestURI();
        if (path.startsWith("/auth/login") || 
            path.startsWith("/auth/logout") ||
            path.contains("/actuator")) {
            chain.doFilter(request, response);
            return;
        }

        SecurityContext securityContext = (SecurityContext) request.getAttribute("SPRING_SECURITY_CONTEXT");

        // Not authenticated via Spring Security - skip check
        if (securityContext == null) {
            chain.doFilter(request, response);
            return;
        }

        Authentication authentication = securityContext.getAuthentication();

        // Not authenticated or principal is null - allow pass through
        if (authentication == null || !authentication.isAuthenticated()) {
            chain.doFilter(request, response);
            return;
        }

        // Get the user from authentication context
        User currentUser = null;

        try {
            Object principal = authentication.getPrincipal();
            if (principal instanceof User) {
                currentUser = ((User) principal);
            }
        } catch (Exception ignored) {}

        // If we still don't have user, check session
        if (currentUser == null) {
            HttpSession httpSession = httpRequest.getSession(false);
            if (httpSession != null) {
                Object currentUserObj = httpSession.getAttribute("currentUser");
                if (currentUserObj instanceof User) {
                    currentUser = ((User) currentUserObj);
                }
            }
        }

        // Check for temporary password - redirect if needed
        if (currentUser != null && currentUser.getIsTempPassword()) {
            httpResponse.sendRedirect(httpRequest.getContextPath() + "/auth/reset-password");
            return;
        }

        chain.doFilter(request, response);
    }
}
