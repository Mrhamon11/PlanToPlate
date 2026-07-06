package com.plantoplate.service;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

import java.util.Optional;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

import com.plantoplate.dto.LoginRequest;
import com.plantopplate.entity.User;
import com.plantopplate.repository.UserRepository;

class AuthServiceTest {

    @Autowired private BCryptPasswordEncoder passwordEncoder;
    @MockBean private UserRepository userRepository;
    @MockBean private AuthenticationManager authenticationManager;

    @BeforeEach
    void setUp() {}

    private AuthService createService() {
        return new AuthService(userRepository, passwordEncoder, authenticationManager);
    }

    @Test
    @DisplayName("authenticateUser - returns user on valid credentials")
    void shouldAuthenticateValidUser() {
        User user = createUser();
        when(authenticationManager.authenticate(any())).thenReturn(Optional.of(user));

        assertThat(createService().authenticateUser(new LoginRequest("testuser", "password")))
                .isEqualTo(user);
    }

    @Test
    @DisplayName("authenticateUser - throws BadCredentialsException on invalid password")
    void shouldThrowOnInvalidPassword() {
        when(authenticationManager.authenticate(any())).thenThrow(
                new org.springframework.security.core.BadCredentialsException("Invalid credentials")
        );

        assertThatThrownBy(() -> createService().authenticateUser(new LoginRequest("testuser", "wrong")))
                .isInstanceOf(org.springframework.security.core.AuthenticationException.class);
    }

    @Test
    @DisplayName("authenticateUser - throws AccountDisabledException on disabled user")
    void shouldThrowOnDisabledUser() {
        User user = createUser();
        user.setIsDisabled(true);
        when(authenticationManager.authenticate(any())).thenThrow(
                new org.springframework.security.core.AuthenticationDisabledException("Account disabled")
        );

        assertThatThrownBy(() -> createService().authenticateUser(new LoginRequest("testuser", "password")))
                .isInstanceOf(org.springframework.security.core.AuthenticationDisabledException.class);
    }

    @Test
    @DisplayName("generateNewPasswordHash - creates valid bcrypt hash")
    void shouldGenerateValidPasswordHash() {
        String newPassword = "newpassword123!@#";
        String hashed = createService().generateNewPasswordHash(newPassword);

        assertThat(passwordEncoder.matches(newPassword, hashed)).isTrue();
        assertThat(hashed).hasLength(greaterThan(60));
    }

    @Test
    @DisplayName("updateTempPassword - returns user with new password")
    void shouldUpdateTempPassword() {
        User user = createUser();
        user.setIsTempPassword(true);
        user.setPasswordHash(passwordEncoder.encode("oldpassword"));

        when(userRepository.save(any())).thenAnswer(i -> i.getArguments()[0]);

        String newPassword = "newpassword123!@#";
        User result = createService().updateTempPassword(user, newPassword);

        assertThat(result.getPasswordHash()).isNotEqualTo("oldpassword");
        assertThat(passwordEncoder.matches(newPassword, result.getPasswordHash())).isTrue();
    }

    @Test
    @DisplayName("updateTempPassword - throws exception on non-temp password")
    void shouldThrowOnNonTempPassword() {
        User user = createUser();
        user.setIsTempPassword(false);
        when(userRepository.save(any())).thenAnswer(i -> i.getArguments()[0]);

        assertThatThrownBy(() -> createService().updateTempPassword(user, "newpassword"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("Only users with temporary passwords can reset password");
    }

    private User createUser() {
        return new User();
    }
}
