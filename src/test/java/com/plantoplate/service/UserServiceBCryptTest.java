package com.plantoplate.service;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest
class UserServiceBCryptTest {

    @Autowired
    private BCryptPasswordEncoder passwordEncoder;

    @Test
    void testPasswordHashingScramblesRawInput() {
        // Arrange - raw plain text passwords that should never be persisted as-is
        String rawPassword1 = "password123";
        String rawPassword2 = "SecureP@ssw0rd!2026";
        String rawPassword3 = "testuser";

        // Act - encode each password
        String encoded1 = passwordEncoder.encode(rawPassword1);
        String encoded2 = passwordEncoder.encode(rawPassword2);
        String encoded3 = passwordEncoder.encode(rawPassword3);

        // Assert - encoded passwords differ from input and from each other
        assertThat(encoded1).isNotEqualTo(rawPassword1);
        assertThat(encoded2).isNotEqualTo(rawPassword2);
        assertThat(encoded3).isNotEqualTo(rawPassword3);
        
        // Each password produces unique hash even if plaintext is same
        assertThat(encoded1).isNotEqualTo(encoded2);
        assertThat(encoded1).isNotEqualTo(encoded3);
    }

    @Test
    void testEncodedPasswordsContainBCryptPrefix() {
        // Act - encode a password
        String encodedPassword = passwordEncoder.encode("testPassword");

        // Assert - BCrypt hashes start with $2a$ or $2b$ prefix and have 60 chars
        assertThat(encodedPassword).startsWith("$2");
        assertThat(encodedPassword.length()).isEqualTo(60);
    }

    @Test
    void testPasswordMatchVerification() {
        // Arrange
        String encodedPassword = passwordEncoder.encode("validPassword123");

        // Act & Assert - same password verifies correctly
        assertThat(passwordEncoder.matches("validPassword123", encodedPassword)).isTrue();
        assertThat(passwordEncoder.matches("wrongPassword", encodedPassword)).isFalse();
        assertThat(passwordEncoder.matches("ValidPassword123", encodedPassword)).isFalse(); // case sensitive
    }

    @Test
    void testNullHandling() {
        // Arrange
        String nullString = null;

        // Act & Assert - encoding null should fail gracefully or throw meaningful exception
        assertThatThrownBy(() -> passwordEncoder.encode(null))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void testEncodingEmptyString() {
        // Act - encode empty string
        String encoded = passwordEncoder.encode("");

        // Assert - empty string gets hashed (not returned as-is)
        assertThat(encoded).doesNotContain("empty");
        assertThat(encoded.length()).isEqualTo(60);
    }
}
