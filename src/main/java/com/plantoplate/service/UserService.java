package com.plantoplate.service;

import com.plantoplate.model.User;
import com.plantoplate.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;

/**
 * Service for managing user creation and seeding default admin accounts.
 */
@Component
public class UserService {

    private final UserRepository userRepository;
    private final BCryptPasswordEncoder passwordEncoder;

    @Autowired
    public UserService(UserRepository userRepository, BCryptPasswordEncoder passwordEncoder) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
    }

    /**
     * Creates an admin user if one doesn't already exist (seed data).
     */
    public void createAdminUser() {
        // Only create admin user if none exists
        if (userRepository.findByUsername("admin") == null) {
            User admin = new User();
            admin.setUsername("admin");
            admin.setPasswordHash(passwordEncoder.encode("testadmin"));
            admin.setRole(User.Role.ADMIN);
            admin.setIsTempPassword(false);
            userRepository.save(admin);
        }
    }

    /**
     * Creates a regular user.
     */
    public void createUser(String username, String password, User.Role role, boolean isTempPassword) {
        if (userRepository.findByUsername(username) == null) {
            User user = new User();
            user.setUsername(username);
            user.setPasswordHash(passwordEncoder.encode(password));
            user.setRole(role);
            user.setIsTempPassword(isTempPassword);
            userRepository.save(user);
        }
    }

    /**
     * Finds a user by username.
     */
    public User findByUsername(String username) {
        return userRepository.findByUsername(username);
    }
}
