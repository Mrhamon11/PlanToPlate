package com.plantoplate.service;

import com.plantoplate.dto.LoginRequest;
import com.plantoplate.model.User;
import com.plantoplate.repository.UserRepository;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

import java.util.Optional;

@Service("authService")
public class AuthService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final AuthenticationManager authenticationManager;

    public AuthService(UserRepository userRepository, 
                       PasswordEncoder passwordEncoder,
                       AuthenticationManager authenticationManager) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
        this.authenticationManager = authenticationManager;
    }

    public User authenticateUser(LoginRequest loginRequest) {
        try {
            Authentication authentication = authenticationManager.authenticate(
                    new org.springframework.security.authentication.UsernamePasswordAuthenticationToken(
                            loginRequest.username(), 
                            loginRequest.password())
            );
            
            User user = userRepository.findByUsername(authentication.getPrincipal().toString());
            if (user == null) {
                throw new RuntimeException("User not found");
            }
            return user;
        } catch (org.springframework.security.core.AuthenticationException e) {
            throw new RuntimeException("Authentication failed: " + e.getMessage(), e);
        }
    }

    public String generateNewPasswordHash(String newPassword) {
        return passwordEncoder.encode(newPassword);
    }

    public User updateTempPassword(User user, String newPassword) {
        if (user.getIsTempPassword()) {
            user.setPasswordHash(passwordEncoder.encode(newPassword));
            return userRepository.save(user);
        } else {
            throw new IllegalArgumentException("Only users with temporary passwords can reset password");
        }
    }

    public Optional<User> findByUsername(String username) {
        User user = userRepository.findByUsername(username);
        if (user != null) {
            return Optional.of(user);
        }
        return Optional.empty();
    }
}
